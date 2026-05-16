"""Kurulum sırasında Postfix/Dovecot + panel ağını otomatik hizalar (Coolify dahil)."""
from __future__ import annotations

import logging
import os
from typing import Any

from installer.compose_builder import JIR_NETWORK
from installer.mail_stack import (
    mail_stack_params_summary,
    provision_mail_stack_docker,
    resolve_mail_stack_params,
)
from management.docker_containers import persist_container_alias
from management.mail_service_endpoint import resolve_mail_endpoint, tcp_reachable

logger = logging.getLogger(__name__)


def _panel_container_name() -> str:
    return (os.getenv('COOLIFY_CONTAINER_NAME') or os.getenv('HOSTNAME') or '').strip()


def _attach_to_network(client: Any, container_name: str, network: str) -> tuple[bool, str]:
    """Panel konteynerini mail ağına bağla (zaten bağlıysa OK)."""
    if not container_name:
        return False, 'Panel konteyner adı bulunamadı (COOLIFY_CONTAINER_NAME / HOSTNAME).'
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

    client = docker_client or _get_docker_client_optional()
    if client is None:
        return {
            'success': False,
            'error': 'Docker API yok — otomatik mail kurulumu yapılamıyor.',
            'messages': messages,
        }

    network = JIR_NETWORK
    panel = _panel_container_name()
    if panel:
        messages.append(f'Panel konteyneri: {panel}')

    try:
        existing = [n for n in client.networks.list(names=[network]) if n.name == network]
        if not existing:
            client.networks.create(network, driver='bridge')
            messages.append(f'Ağ oluşturuldu: {network}')
        else:
            messages.append(f'Ağ mevcut: {network}')
    except Exception as exc:
        return {'success': False, 'error': f'Ağ hazırlığı: {exc}', 'messages': messages}

    need_provision = not _mail_containers_running(client)
    if need_provision:
        messages.append('Postfix/Dovecot kuruluyor…')
        prov = provision_mail_stack_docker(
            skip_busy_ports=skip_busy_ports,
            pull_images=True,
            mail_domain_override=domain or None,
            mail_hostname_override=mail_hostname or None,
            docker_network_override=network,
        )
        messages.extend(prov.get('messages') or [])
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
        messages.append('Postfix ve Dovecot zaten çalışıyor.')

    if panel:
        ok, msg = _attach_to_network(client, panel, network)
        messages.append(msg)
        if not ok:
            return {
                'success': False,
                'error': f'Panel mail ağına bağlanamadı: {msg}',
                'messages': messages,
            }
    else:
        messages.append(
            'Uyarı: Panel konteyner adı bilinmiyor; mail DNS panel yeniden başlatılınca denenecek.'
        )

    smtp_host, imap_host = 'jir_postfix', 'jir_dovecot'
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

    # Panel ağa yeni bağlandıysa DNS kısa süre gecikebilir; resolve_mail_endpoint yedek dener.
    smtp_ok = tcp_reachable(smtp_host, smtp_port, timeout=3.0)
    imap_ok = tcp_reachable(imap_host, imap_port, timeout=3.0)
    if not smtp_ok or not imap_ok:
        rh, rp = resolve_mail_endpoint('postfix', smtp_port, auth_submission=True)
        ih, ip = resolve_mail_endpoint('dovecot', imap_port)
        smtp_ok = smtp_ok or tcp_reachable(rh, rp, timeout=3.0)
        imap_ok = imap_ok or tcp_reachable(ih, ip, timeout=3.0)
        if smtp_ok:
            smtp_host, smtp_port = rh, rp
        if imap_ok:
            imap_host, imap_port = ih, ip

    mail_endpoints = {
        'smtp_host': smtp_host,
        'smtp_port': smtp_port,
        'imap_host': imap_host,
        'imap_port': imap_port,
        'docker_network': network,
        'panel_container': panel,
    }

    if smtp_ok and imap_ok:
        messages.append(f'SMTP hazır: {smtp_host}:{smtp_port}')
        messages.append(f'IMAP hazır: {imap_host}:{imap_port}')
        return {
            'success': True,
            'messages': messages,
            'mail_endpoints': mail_endpoints,
            'docker_container_map': {
                'postfix': smtp_host if smtp_host.startswith('jir_') else 'jir_postfix',
                'dovecot': imap_host if imap_host.startswith('jir_') else 'jir_dovecot',
            },
            'params': params_summary,
        }

    return {
        'success': False,
        'error': (
            f'Mail TCP doğrulanamadı (SMTP {smtp_host}:{smtp_port}, IMAP {imap_host}:{imap_port}). '
            'Kurulum yeniden denenecek veya redeploy sonrası otomatik düzelir.'
        ),
        'messages': messages,
        'mail_endpoints': mail_endpoints,
        'smtp_ok': smtp_ok,
        'imap_ok': imap_ok,
    }


def apply_mail_connectivity_to_system_config(result: dict[str, Any]) -> None:
    """Kurulum sonucunu SystemConfig + ortam için kalıcı kaydet."""
    try:
        from saas.models import SystemConfig

        conf = SystemConfig.objects.first()
        if not conf:
            return
        ep = result.get('mail_endpoints') or {}
        dmap = result.get('docker_container_map') or {}
        if dmap:
            merged = dict(conf.docker_container_map or {})
            merged.update({str(k): str(v) for k, v in dmap.items() if k and v})
            conf.docker_container_map = merged
        log = dict(conf.installation_log or {})
        log['mail_endpoints'] = ep
        log['mail_auto_setup'] = {
            'success': result.get('success'),
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
