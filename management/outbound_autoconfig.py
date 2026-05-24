"""Dış posta çıkışını otomatik yapılandır — port 25, relay, transport maps."""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from django.conf import settings

from management.outbound_connectivity import (
    OUTBOUND_PROBE_TARGETS,
    check_outbound_smtp,
    get_postfix_relayhost,
    tcp_probe_from_postfix,
)

logger = logging.getLogger(__name__)

CONFIG_PATH = Path('/app/config/outbound_delivery.json')
CACHE_TTL_SEC = 120.0
_last_run_at: float = 0.0
_last_report: dict[str, Any] | None = None

POSTFIX_INIT_SCRIPTS = (
    '/docker-init.d/10-jirmail-inbound.sh',
    '/docker-init.d/31-jirmail-transport-maps.sh',
    '/docker-init.d/30-jirmail-outbound-smtp.sh',
    '/docker-init.d/32-jirmail-relay-sasl.sh',
)


def _postfix_container_name() -> str:
    return (os.getenv('JIR_CONTAINER_POSTFIX') or 'jir_postfix').strip()


def _docker_client():
    import docker

    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=15)


def resolve_relay_config() -> dict[str, str]:
    """Relay ayarlarını env, settings ve kalıcı config'den çöz."""
    relayhost = (getattr(settings, 'SMTP_RELAYHOST', '') or os.getenv('SMTP_RELAYHOST', '') or '').strip()
    host = (getattr(settings, 'SMTP_RELAY_HOST', '') or os.getenv('SMTP_RELAY_HOST', '') or '').strip()
    port = (getattr(settings, 'SMTP_RELAY_PORT', '') or os.getenv('SMTP_RELAY_PORT', '') or '587').strip()
    user = (getattr(settings, 'SMTP_RELAY_USER', '') or os.getenv('SMTP_RELAY_USER', '') or '').strip()
    password = (
        getattr(settings, 'SMTP_RELAY_PASSWORD', '') or os.getenv('SMTP_RELAY_PASSWORD', '') or ''
    ).strip()

    if not relayhost and host:
        relayhost = f'[{host}]:{port or "587"}'

    if CONFIG_PATH.is_file():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
            relay = saved.get('relay') or {}
            relayhost = relayhost or (relay.get('relayhost') or '').strip()
            user = user or (relay.get('user') or '').strip()
            password = password or (relay.get('password') or '').strip()
        except Exception as exc:
            logger.debug('outbound_delivery.json okunamadı: %s', exc)

    try:
        from saas.models import SystemConfig

        conf = SystemConfig.objects.only('installation_log').first()
        if conf and conf.installation_log:
            relay = (conf.installation_log.get('outbound_relay') or {})
            relayhost = relayhost or (relay.get('relayhost') or '').strip()
            user = user or (relay.get('user') or '').strip()
            password = password or (relay.get('password') or '').strip()
    except Exception as exc:
        logger.debug('installation_log relay okunamadı: %s', exc)

    return {
        'relayhost': relayhost,
        'user': user,
        'password': password,
    }


def _persist_state(report: dict[str, Any]) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            'updated_at': time.time(),
            'mode': report.get('mode'),
            'relayhost': report.get('relayhost') or '',
            'port25_ok': report.get('port25_ok'),
            'relay': resolve_relay_config(),
        }
        CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as exc:
        logger.debug('outbound state yazılamadı: %s', exc)


def _fix_reserved_domains() -> list[str]:
    """Yanlış eklenmiş Gmail/Proton vb. domainleri pasifleştir."""
    try:
        from core.mail_domains import is_reserved_public_domain, normalize_domain
        from core.models import MailDomain
        from management.postfix_maps import reload_virtual_mailboxes

        fixed: list[str] = []
        for dom in MailDomain.objects.filter(is_active=True):
            name = normalize_domain(dom.name)
            if not name or not is_reserved_public_domain(name):
                continue
            dom.is_active = False
            dom.save(update_fields=['is_active'])
            fixed.append(name)
        if fixed:
            reload_virtual_mailboxes()
            applied = apply_postfix_outbound_scripts()
            logger.info('reserved domain fix: postfix init %s', applied.get('ok'))
        return fixed
    except Exception as exc:
        logger.warning('reserved domain fix: %s', exc)
        return []


def apply_postfix_outbound_scripts(*, container: str | None = None) -> dict[str, Any]:
    """Postfix init script'lerini çalıştır (transport + outbound + relay SASL)."""
    name = container or _postfix_container_name()
    out: dict[str, Any] = {'container': name, 'ok': True, 'actions': []}
    try:
        client = _docker_client()
        c = client.containers.get(name)
        for script in POSTFIX_INIT_SCRIPTS:
            code, logs = c.exec_run(['sh', script], demux=True)
            stderr = (logs[1] or b'').decode()[:500]
            stdout = (logs[0] or b'').decode()[:300]
            out['actions'].append(
                {'script': script, 'exit_code': code, 'stdout': stdout, 'stderr': stderr}
            )
            if code != 0:
                out['ok'] = False
        client.close()
    except Exception as exc:
        out['ok'] = False
        out['error'] = str(exc)
        logger.warning('apply_postfix_outbound_scripts: %s', exc)
    return out


def port25_reachable_from_postfix(*, container: str | None = None) -> bool:
    host, port, _label = OUTBOUND_PROBE_TARGETS[0]
    ok, _msg, _name = tcp_probe_from_postfix(host, port, container=container)
    return ok


def ensure_outbound_delivery(
    *,
    fix: bool = True,
    force: bool = False,
    full_heal: bool = False,
) -> dict[str, Any]:
    """Port 25 / relay / transport maps otomatik yapılandır.

    full_heal=True: Postfix init script'leri (deploy/cron — yavaş).
    full_heal=False: yalnızca DB/domain düzeltmesi + hızlı probe (gönderim yolu).
    """
    global _last_run_at, _last_report

    now = time.time()
    if not force and _last_report and (now - _last_run_at) < CACHE_TTL_SEC:
        return _last_report

    report: dict[str, Any] = {
        'ok': True,
        'mode': 'direct',
        'relayhost': '',
        'port25_ok': False,
        'actions': [],
        'fixed_domains': [],
        'message': '',
    }

    if fix:
        report['fixed_domains'] = _fix_reserved_domains()
        if full_heal:
            applied = apply_postfix_outbound_scripts()
            report['actions'].append({'postfix_init': applied})

    relay_cfg = resolve_relay_config()
    env_relay = relay_cfg.get('relayhost') or ''
    port25_ok = port25_reachable_from_postfix()
    report['port25_ok'] = port25_ok

    current_relay = get_postfix_relayhost()

    if env_relay:
        report['mode'] = 'relay'
        report['relayhost'] = env_relay
        report['message'] = f'Relay yapılandırıldı: {env_relay}'
        if fix and current_relay != env_relay and full_heal:
            apply_postfix_outbound_scripts()
    elif port25_ok:
        report['mode'] = 'direct'
        report['relayhost'] = ''
        report['message'] = 'Doğrudan port 25 çıkışı kullanılıyor'
    else:
        report['mode'] = 'direct_blocked'
        report['ok'] = False
        report['message'] = (
            'Port 25 kapalı ve SMTP relay tanımlı değil. '
            'Gönderim denenecek; kalıcı teslimat için .env içine '
            'SMTP_RELAYHOST veya SMTP_RELAY_HOST/PORT/USER/PASSWORD ekleyin.'
        )

    outbound = check_outbound_smtp(include_django_probe=False)
    if outbound.get('mode') == 'relay' or outbound.get('ok'):
        report['ok'] = True
        report['mode'] = outbound.get('mode') or report['mode']
        report['relayhost'] = outbound.get('relayhost') or report['relayhost']

    _persist_state(report)
    _last_run_at = now
    _last_report = report
    return report
