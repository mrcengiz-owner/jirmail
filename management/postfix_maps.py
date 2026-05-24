"""Postfix virtual_mailbox_maps yenileme (hesap ekleme/silme sonrası)."""
from __future__ import annotations

import base64
import logging
import os
import subprocess
from typing import Any

logger = logging.getLogger(__name__)

JIR_POSTFIX_MAPS_VERSION = 3

PGSQL_MAP_FILES: tuple[tuple[str, str], ...] = (
    ('/etc/postfix/pgsql-virtual-mailboxes.cf', 'mailbox'),
    ('/etc/postfix/pgsql-virtual-domains.cf', 'virtual-domains'),
    ('/etc/postfix/pgsql-transport-maps.cf', 'transport-maps'),
)


def _postfix_container_name() -> str:
    return (os.getenv('JIR_CONTAINER_POSTFIX') or 'jir_postfix').strip()


def _docker_client():
    import docker
    from django.conf import settings

    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=30)


def _resolve_postfix_db_config() -> dict[str, str]:
    from django.conf import settings

    db = settings.DATABASES.get('default', {})
    return {
        'db_host': (os.getenv('DB_HOST') or db.get('HOST') or 'postgres').strip(),
        'db_port': str(os.getenv('DB_PORT') or db.get('PORT') or '5432').strip(),
        'db_user': (os.getenv('DB_USER') or os.getenv('POSTGRES_USER') or db.get('USER') or 'postgres').strip(),
        'db_pass': (os.getenv('DB_PASS') or os.getenv('POSTGRES_PASSWORD') or db.get('PASSWORD') or '').strip(),
        'db_name': (
            os.getenv('DB_NAME')
            or os.getenv('POSTGRES_DB')
            or db.get('NAME')
            or 'jir_mail_prod'
        ).strip(),
    }


def _map_query(kind: str) -> str:
    from core.mail_domains import (
        HOSTED_DOMAIN_SQL,
        HOSTED_DOMAIN_TRANSPORT_SQL,
        HOSTED_MAILBOX_SQL,
    )

    if kind == 'mailbox':
        return HOSTED_MAILBOX_SQL
    if kind == 'virtual-domains':
        return HOSTED_DOMAIN_SQL
    if kind == 'transport-maps':
        return HOSTED_DOMAIN_TRANSPORT_SQL
    raise ValueError(f'bilinmeyen map türü: {kind}')


def build_postfix_pgsql_map_content(*, kind: str, db: dict[str, str] | None = None) -> str:
    from management.mail_stack_health import build_postfix_pgsql_cf

    cfg = db or _resolve_postfix_db_config()
    body = build_postfix_pgsql_cf(
        db_host=cfg['db_host'],
        db_port=cfg['db_port'],
        db_user=cfg['db_user'],
        db_pass=cfg['db_pass'],
        db_name=cfg['db_name'],
        query=_map_query(kind),
    )
    return f'# JIR_POSTFIX_MAPS_VERSION={JIR_POSTFIX_MAPS_VERSION}\n{body}'


def _write_file_in_container(c, dest: str, content: str) -> dict[str, Any]:
    encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
    cmd = (
        f'echo {encoded} | base64 -d > {dest} && chmod 600 {dest} && '
        f'grep -q "^query = " {dest}'
    )
    code, logs = c.exec_run(['sh', '-c', cmd], demux=True)
    stderr = (logs[1] or b'').decode()[:300]
    stdout = (logs[0] or b'').decode()[:200]
    return {'dest': dest, 'exit_code': code, 'stdout': stdout, 'stderr': stderr, 'ok': code == 0}


def rewrite_postfix_pgsql_maps(*, container: str | None = None) -> dict[str, Any]:
    """Init script sürümünden bağımsız — doğru pgsql map dosyalarını doğrudan yazar."""
    name = container or _postfix_container_name()
    out: dict[str, Any] = {'container': name, 'ok': False, 'actions': []}
    db = _resolve_postfix_db_config()
    try:
        client = _docker_client()
        c = client.containers.get(name)
        for dest, kind in PGSQL_MAP_FILES:
            content = build_postfix_pgsql_map_content(kind=kind, db=db)
            action = _write_file_in_container(c, dest, content)
            out['actions'].append({'write': dest, **action})
            if not action['ok']:
                out['error'] = f'{dest} yazılamadı'
                client.close()
                return out

        postconf_cmds = [
            'virtual_mailbox_domains=pgsql:/etc/postfix/pgsql-virtual-domains.cf',
            'virtual_mailbox_maps=pgsql:/etc/postfix/pgsql-virtual-mailboxes.cf',
            'transport_maps=pgsql:/etc/postfix/pgsql-transport-maps.cf',
            'virtual_transport=lmtp:inet:dovecot:24',
            'default_transport=smtp',
            'relay_transport=smtp',
            'relay_domains=',
        ]
        for pc in postconf_cmds:
            code, logs = c.exec_run(['postconf', '-e', pc], demux=True)
            out['actions'].append(
                {
                    'postconf': pc,
                    'exit_code': code,
                    'stderr': (logs[1] or b'').decode()[:200],
                }
            )

        code, logs = c.exec_run(['postfix', 'reload'], demux=True)
        out['actions'].append(
            {
                'postfix_reload': code == 0,
                'stderr': (logs[1] or b'').decode()[:200],
            }
        )
        client.close()
        out['ok'] = True
    except Exception as exc:
        out['error'] = str(exc)
        logger.warning('rewrite_postfix_pgsql_maps: %s', exc)
    return out


def force_fix_postfix_routing(*, container: str | None = None) -> dict[str, Any]:
    """Gmail → Dovecot hatası: DB temizliği + map rewrite + routing probe."""
    from management.outbound_autoconfig import (
        _fix_reserved_domains,
        apply_postfix_outbound_scripts,
        probe_postfix_recipient_routing,
    )

    report: dict[str, Any] = {
        'ok': False,
        'fixed_domains': [],
        'rewrite': {},
        'routing': {},
        'outbound': {},
    }
    report['fixed_domains'] = _fix_reserved_domains()
    report['rewrite'] = rewrite_postfix_pgsql_maps(container=container)
    if report['rewrite'].get('ok'):
        report['outbound'] = apply_postfix_outbound_scripts(container=container)
    report['routing'] = probe_postfix_recipient_routing(domain='gmail.com')
    report['ok'] = bool(report['rewrite'].get('ok')) and bool(report['routing'].get('ok'))
    return report


def reload_virtual_mailboxes() -> bool:
    """Postfix yenile (pgsql harita anlık; docker yoksa no-op)."""
    try:
        from core.mail_provision import reload_postfix

        reload_postfix()
        return True
    except Exception as exc:
        logger.debug('postfix reload: %s', exc)

    rewritten = rewrite_postfix_pgsql_maps()
    if rewritten.get('ok'):
        return True

    container = _postfix_container_name()
    script = '/docker-init.d/10-jirmail-inbound.sh'
    transport_script = '/docker-init.d/31-jirmail-transport-maps.sh'
    try:
        result = subprocess.run(
            ['docker', 'exec', container, 'sh', script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                'Postfix virtual_mailbox yenileme: %s',
                (result.stderr or result.stdout or '')[:500],
            )
            return False
        subprocess.run(
            ['docker', 'exec', container, 'sh', transport_script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return True
    except FileNotFoundError:
        logger.debug('docker CLI yok — postfix map yenileme atlandı (pgsql canlı)')
        return True
    except Exception as exc:
        logger.warning('Postfix virtual_mailbox yenileme: %s', exc)
        return False
