"""Kurulum sırasında Postfix/Dovecot + panel ağını otomatik hizalar."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

from installer.compose_builder import JIR_NETWORK
from installer.compose_mode import ensure_runtime_mail_ca, is_compose_stack
from installer.docker_images import dovecot_container_needs_rebuild
from installer.mail_stack import (
    mail_stack_params_summary,
    provision_mail_stack_docker,
    resolve_mail_stack_params,
)
from management.docker_containers import persist_container_alias
from installer.mail_pki import ensure_mail_pki_volume
from management.mail_service_endpoint import resolve_mail_endpoint, tcp_reachable
from management.mail_tls import verify_imap_tls, verify_smtp_starttls

logger = logging.getLogger(__name__)

MAIL_TCP_WAIT_SEC = float(os.getenv('MAIL_TCP_WAIT_SEC', '90'))
MAIL_TCP_POLL_SEC = float(os.getenv('MAIL_TCP_POLL_SEC', '2'))


def _panel_container_name() -> str:
    return (os.getenv('COOLIFY_CONTAINER_NAME') or os.getenv('HOSTNAME') or '').strip()


def _attach_to_network(client: Any, container_name: str, network: str) -> tuple[bool, str]:
    """Panel konteynerini mail ağına bağla (zaten bağlıysa OK)."""
    if not container_name:
        return False, 'Panel konteyner adı bulunamadı (HOSTNAME / COOLIFY_CONTAINER_NAME).'
    try:
        container = client.containers.get(container_name)
    except Exception as exc:
        return False, f'Panel konteyneri bulunamadı ({container_name}): {exc}'

    try:
        nets = (container.attrs.get('NetworkSettings') or {}).get('Networks') or {}
        if network in nets:
            return True, f'{container_name} zaten {network} ağında.'
    except Exception:
        pass

    try:
        network_obj = client.networks.get(network)
        network_obj.connect(container, aliases=[container_name.split('-')[0][:32]])
        return True, f'{container_name} → {network} ağına bağlandı.'
    except Exception as exc:
        err = str(exc).lower()
        if 'already exists' in err or 'already connected' in err:
            return True, f'{container_name} zaten {network} üzerinde.'
        return False, str(exc)


def _mail_containers_running(client: Any) -> bool:
    try:
        pf = client.containers.get('jir_postfix')
        dv = client.containers.get('jir_dovecot')
        return pf.status == 'running' and dv.status == 'running'
    except Exception:
        return False


def _ensure_db_container_on_network(client: Any, db_host: str, network: str) -> str | None:
    """Dovecot passdb için Postgres konteynerini mail ağına bağla."""
    host = (db_host or '').strip()
    if not host or host in ('localhost', '127.0.0.1'):
        return None
    try:
        container = client.containers.get(host)
    except Exception:
        return f'Postgres konteyneri bulunamadı ({host}); DATABASE_URL host adını kontrol edin.'
    try:
        nets = (container.attrs.get('NetworkSettings') or {}).get('Networks') or {}
        if network in nets:
            return f'Veritabanı {host} zaten {network} ağında.'
        client.networks.get(network).connect(container)
        return f'Veritabanı {host} → {network} ağına bağlandı (Dovecot erişimi).'
    except Exception as exc:
        err = str(exc).lower()
        if 'already' in err:
            return f'Veritabanı {host} zaten {network} üzerinde.'
        return f'Veritabanı ağ bağlantısı ({host}): {exc}'


def _dovecot_container_healthy(client: Any, name: str) -> bool:
    try:
        c = client.containers.get(name)
        c.reload()
        if getattr(c, 'status', '') != 'running':
            return False
        exit_code, _ = c.exec_run(
            ['doveconf', '-n'],
            demux=True,
        )
        if exit_code != 0:
            return False
        exit_code2, out = c.exec_run(
            ['grep', '-q', '^driver = pgsql', '/etc/dovecot/dovecot-sql.conf.ext'],
            demux=True,
        )
        return exit_code2 == 0
    except Exception:
        return False


def _needs_mail_provision(client: Any, postfix_name: str, dovecot_name: str) -> bool:
    if not _mail_containers_running(client):
        return True
    if dovecot_container_needs_rebuild(client, dovecot_name):
        return True
    if not _dovecot_container_healthy(client, dovecot_name):
        return True
    return False


def _wait_mail_tcp(host: str, port: int, *, timeout: float = MAIL_TCP_WAIT_SEC) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if tcp_reachable(host, port, timeout=2.5):
            return True
        time.sleep(MAIL_TCP_POLL_SEC)
    return False


def _verify_mail_endpoints(
    smtp_host: str,
    smtp_port: int,
    imap_host: str,
    imap_port: int,
) -> tuple[bool, bool, str, int, str, int, list[str]]:
    """TCP + zorunlu TLS (STARTTLS / IMAPS) doğrulaması."""
    smtp_ok = False
    imap_ok = False
    imap_tcp = False
    hints: list[str] = []
    deadline = time.monotonic() + MAIL_TCP_WAIT_SEC
    while time.monotonic() < deadline:
        if not smtp_ok and tcp_reachable(smtp_host, smtp_port, timeout=2.5):
            smtp_ok = verify_smtp_starttls(smtp_host, smtp_port)
        if not imap_ok:
            imap_tcp = tcp_reachable(imap_host, imap_port, timeout=2.5)
            if imap_tcp:
                imap_ok = verify_imap_tls(imap_host, imap_port, log_failure=True)
        if smtp_ok and imap_ok:
            break
        time.sleep(MAIL_TCP_POLL_SEC)

    if smtp_ok and imap_ok:
        return smtp_ok, imap_ok, smtp_host, smtp_port, imap_host, imap_port, hints

    rh, rp = resolve_mail_endpoint('postfix', smtp_port, auth_submission=True)
    ih, ip = resolve_mail_endpoint('dovecot', imap_port)
    if not smtp_ok and verify_smtp_starttls(rh, rp):
        smtp_ok, smtp_host, smtp_port = True, rh, rp
    if not imap_ok:
        imap_tcp = tcp_reachable(ih, ip, timeout=2.5)
        if imap_tcp and verify_imap_tls(ih, ip, log_failure=True):
            imap_ok, imap_host, imap_port = True, ih, ip

    if not imap_ok:
        if not imap_tcp:
            hints.append(
                f'IMAP TCP kapalı ({imap_host}:{imap_port}): jir_dovecot çalışıyor mu, '
                '993 dinliyor mu? → docker ps -a | grep dovecot; '
                'docker exec jir_dovecot doveconf -n; docker exec jir_dovecot ss -lntp'
            )
        else:
            hints.append(
                f'IMAP TCP açık ama TLS/CA doğrulaması başarısız ({imap_host}:{imap_port}). '
                'jir_mail_tls volume ve panel MAIL_TLS_CA_FILE kontrol edin.'
            )

    return smtp_ok, imap_ok, smtp_host, smtp_port, imap_host, imap_port, hints


def auto_setup_mail_services(
    config: dict[str, Any],
    *,
    docker_client: Any | None = None,
    skip_busy_ports: bool = True,
) -> dict[str, Any]:
    """Postfix+Dovecot kur (gerekirse), paneli jir_network'e bağla, TCP doğrula."""
    from installer.orchestrator import _get_docker_client_optional

    messages: list[str] = []
    domain = (config.get('domain') or '').strip()
    mail_hostname = (config.get('mail_hostname') or f'mail.{domain}' if domain else '').strip()

    compose_only = bool(config.get('stack_already_provisioned')) and is_compose_stack()
    client = docker_client or _get_docker_client_optional()
    if client is None and not compose_only:
        return {
            'success': False,
            'error': 'Docker API yok — otomatik mail kurulumu yapılamıyor.',
            'messages': messages,
        }

    network = JIR_NETWORK
    panel = _panel_container_name()
    if panel:
        messages.append(f'Panel konteyneri: {panel}')

    if client is not None:
        try:
            existing = [n for n in client.networks.list(names=[network]) if n.name == network]
            if not existing:
                client.networks.create(network, driver='bridge')
                messages.append(f'Ağ oluşturuldu: {network}')
            else:
                messages.append(f'Ağ mevcut: {network}')
        except Exception as exc:
            return {'success': False, 'error': f'Ağ hazırlığı: {exc}', 'messages': messages}
    elif compose_only:
        messages.append('Compose modu: Docker API atlandı (servisler aynı ağda).')

    if compose_only:
        smtp_host = os.getenv('SMTP_HOST', 'postfix').strip() or 'postfix'
        imap_host = os.getenv('IMAP_HOST', 'dovecot').strip() or 'dovecot'
    else:
        smtp_host, imap_host = 'jir_postfix', 'jir_dovecot'
    try:
        if not compose_only:
            params = resolve_mail_stack_params(mail_domain_override=domain or None)
            smtp_host = params.postfix_container
            imap_host = params.dovecot_container
    except Exception as exc:
        return {'success': False, 'error': str(exc), 'messages': messages}

    pki_ca_pem = (config.get('mail_pki_ca_pem') or '').strip()
    try:
        params_pre = resolve_mail_stack_params(mail_domain_override=domain or None)
        if client is not None:
            db_msg = _ensure_db_container_on_network(client, params_pre.db_host, network)
            if db_msg:
                messages.append(db_msg)
        if not pki_ca_pem:
            messages.append('Dahili mail PKI (TLS)…')
            if compose_only:
                from pathlib import Path
                from installer.mail_pki import MAIL_TLS_MOUNT, ensure_mail_pki_files

                material = ensure_mail_pki_files(
                    Path(MAIL_TLS_MOUNT),
                    mail_hostname=mail_hostname or params_pre.mail_hostname,
                    mail_domain=params_pre.mail_domain,
                    postfix_host=os.getenv('SMTP_HOST', 'postfix'),
                    dovecot_host=os.getenv('IMAP_HOST', 'dovecot'),
                )
                pki_ca_pem = material.ca_cert_pem.decode('utf-8')
                messages.append('TLS sertifikaları hazır (compose volume).')
            else:
                pki = ensure_mail_pki_volume(
                    client,
                    mail_hostname=mail_hostname or params_pre.mail_hostname,
                    mail_domain=params_pre.mail_domain,
                    postfix_container=params_pre.postfix_container,
                    dovecot_container=params_pre.dovecot_container,
                )
                pki_ca_pem = pki.ca_cert_pem.decode('utf-8')
                messages.append('TLS sertifikaları hazır (jir_mail_tls volume).')
        else:
            messages.append('TLS sertifikaları mevcut (bootstrap).')
    except Exception as exc:
        messages.append(f'PKI/TLS: {exc}')
        return {
            'success': False,
            'error': f'Mail PKI hazırlanamadı: {exc}',
            'messages': messages,
        }

    if panel and client is not None:
        ok, msg = _attach_to_network(client, panel, network)
        messages.append(msg)
        if not ok:
            return {
                'success': False,
                'error': f'Panel mail ağına bağlanamadı: {msg}',
                'messages': messages,
            }
    elif compose_only:
        messages.append('Compose: panel zaten postfix/dovecot ile aynı ağda.')

    need_provision = False
    if client is not None:
        need_provision = _needs_mail_provision(client, smtp_host, imap_host)
    if config.get('stack_already_provisioned'):
        need_provision = False
        if compose_only:
            messages.append('Mail servisleri Compose stack ile zaten çalışıyor.')
        elif client is not None and _mail_containers_running(client):
            messages.append('Mail konteynerleri docker_stack bootstrap ile zaten kuruldu.')
        else:
            messages.append('Mail stack zaten provision edildi (compose).')
    if need_provision and client is not None:
        if dovecot_container_needs_rebuild(client, imap_host):
            messages.append('Dovecot özel imajına yükseltiliyor (PostgreSQL passdb)…')
        else:
            messages.append('Postfix/Dovecot kuruluyor…')
        from installer.mail_pki import volume_has_mail_pki

        prov = provision_mail_stack_docker(
            skip_busy_ports=skip_busy_ports,
            pull_images=True,
            mail_domain_override=domain or None,
            mail_hostname_override=mail_hostname or None,
            docker_network_override=network,
            skip_pki_setup=bool(pki_ca_pem) or volume_has_mail_pki(client),
        )
        messages.extend(prov.get('messages') or [])
        if not pki_ca_pem and prov.get('tls_ca_pem'):
            pki_ca_pem = prov['tls_ca_pem']
        if not prov.get('success') and prov.get('mode') != 'no_docker':
            return {
                'success': False,
                'error': prov.get('error') or 'Mail stack kurulumu başarısız.',
                'messages': messages,
                'provision': prov,
            }
        if not prov.get('success'):
            return {
                'success': False,
                'error': prov.get('error') or 'Docker ile mail kurulamadı.',
                'messages': messages,
                'provision': prov,
            }
    else:
        messages.append('Postfix ve Dovecot zaten çalışıyor (özel Dovecot imajı).')

    if not panel:
        messages.append(
            'Uyarı: Panel konteyner adı bilinmiyor (HOSTNAME / COOLIFY_CONTAINER_NAME); '
            'SMTP/IMAP DNS çözülemeyebilir.'
        )

    params_summary: dict[str, Any] = {}
    try:
        params = resolve_mail_stack_params(mail_domain_override=domain or None)
        smtp_host = params.postfix_container
        imap_host = params.dovecot_container
        params_summary = mail_stack_params_summary(params)
        for sk, cname in (('postfix', smtp_host), ('dovecot', imap_host)):
            persist_container_alias(sk, cname)
    except Exception as exc:
        logger.debug('mail stack params: %s', exc)

    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    imap_port = int(os.getenv('IMAP_PORT', '993'))

    ensure_runtime_mail_ca(pki_ca_pem)

    messages.append('Mail servisleri hazır olana kadar bekleniyor…')
    smtp_ok, imap_ok, smtp_host, smtp_port, imap_host, imap_port, verify_hints = _verify_mail_endpoints(
        smtp_host, smtp_port, imap_host, imap_port,
    )
    messages.extend(verify_hints)

    mail_endpoints = {
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
        'imap_host': imap_host,
        'imap_port': imap_port,
        'docker_network': network,
        'panel_container': panel,
        'tls_mode': 'e2e',
        'tls_ca_pem': pki_ca_pem,
    }

    result: dict[str, Any] = {
        'messages': messages,
        'mail_endpoints': mail_endpoints,
        'docker_container_map': {
            'postfix': smtp_host if smtp_host.startswith('jir_') else 'jir_postfix',
            'dovecot': imap_host if imap_host.startswith('jir_') else 'jir_dovecot',
        },
        'params': params_summary,
        'smtp_ok': smtp_ok,
        'imap_ok': imap_ok,
    }

    if smtp_ok and imap_ok:
        messages.append(f'SMTP hazır: {smtp_host}:{smtp_port}')
        messages.append(f'IMAP hazır: {imap_host}:{imap_port}')
        messages.append(
            'Mail trafiği uçtan uca TLS ile korunuyor (dahili PKI). Panel HTTPS ayrı katmandır.'
        )
        result['success'] = True
        apply_mail_connectivity_to_system_config(result)
        return result

    result['success'] = False
    result['error'] = (
        f'Mail TLS doğrulanamadı — SMTP {"OK" if smtp_ok else "yok"}, IMAP {"OK" if imap_ok else "yok"} '
        f'({smtp_host}:{smtp_port}, {imap_host}:{imap_port}). '
        'docker logs jir_dovecot && docker logs jir_postfix'
    )
    return result


def apply_mail_connectivity_to_system_config(result: dict[str, Any]) -> None:
    """Kurulum sonucunu SystemConfig + çalışma anı ortamı için kaydet."""
    ep = result.get('mail_endpoints') or {}
    if ep.get('smtp_host'):
        os.environ.setdefault('SMTP_HOST', str(ep['smtp_host']))
    if ep.get('smtp_port'):
        os.environ.setdefault('SMTP_PORT', str(ep['smtp_port']))
    if ep.get('imap_host'):
        os.environ.setdefault('IMAP_HOST', str(ep['imap_host']))
    if ep.get('imap_port'):
        os.environ.setdefault('IMAP_PORT', str(ep['imap_port']))
    if ep.get('tls_ca_pem'):
        try:
            from installer.mail_pki import write_ca_to_path
            from pathlib import Path
            import tempfile

            dest = Path(tempfile.gettempdir()) / 'jir-mail-internal-ca.crt'
            ca_raw = ep['tls_ca_pem']
            ca_bytes = ca_raw.encode('utf-8') if isinstance(ca_raw, str) else ca_raw
            write_ca_to_path(ca_bytes, dest)
            os.environ.setdefault('MAIL_TLS_CA_FILE', str(dest))
        except Exception:
            pass

    try:
        from saas.models import SystemConfig

        conf = SystemConfig.objects.first()
        if not conf:
            return
        dmap = result.get('docker_container_map') or {}
        if dmap:
            merged = dict(conf.docker_container_map or {})
            merged.update({str(k): str(v) for k, v in dmap.items() if k and v})
            conf.docker_container_map = merged
        log = dict(conf.installation_log or {})
        log['mail_endpoints'] = ep
        log['mail_auto_setup'] = {
            'success': result.get('success'),
            'smtp_ok': result.get('smtp_ok'),
            'imap_ok': result.get('imap_ok'),
            'messages': (result.get('messages') or [])[-20:],
        }
        conf.installation_log = log
        conf.save(update_fields=['docker_container_map', 'installation_log', 'updated_at'])
    except Exception as exc:
        logger.warning('mail connectivity SystemConfig kaydı: %s', exc)


def mail_endpoints_from_system_config() -> dict[str, Any]:
    """Çalışma anında kayıtlı SMTP/IMAP uçları (kurulumdan sonra)."""
    try:
        from saas.models import SystemConfig

        conf = SystemConfig.objects.only('installation_log').first()
        if not conf or not conf.installation_log:
            return {}
        ep = conf.installation_log.get('mail_endpoints')
        return ep if isinstance(ep, dict) else {}
    except Exception:
        return {}
