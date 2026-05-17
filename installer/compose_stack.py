"""Tek compose dosyası — panel + Postgres + Redis + Postfix + Dovecot aynı stack."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from installer.compose_mode import ensure_runtime_mail_ca, is_compose_stack
from installer.mail_pki import MAIL_TLS_MOUNT, ensure_mail_pki_files

logger = logging.getLogger(__name__)

__all__ = ['is_compose_stack', 'bootstrap_compose_stack']


def bootstrap_compose_stack(config: dict[str, Any]) -> dict[str, Any]:
    """Compose içinde: PKI + mail TLS doğrula (servisler compose ile zaten ayakta)."""
    from installer.mail_connectivity import (
        apply_mail_connectivity_to_system_config,
        auto_setup_mail_services,
    )

    messages: list[str] = []
    domain = (config.get('domain') or os.getenv('MAIL_DOMAIN') or 'mail.local').strip()
    mail_hostname = (config.get('mail_hostname') or os.getenv('MAIL_HOSTNAME') or f'mail.{domain}').strip()

    messages.append('Kurulum modu: Docker Compose (tüm servisler aynı stack).')
    messages.append('Postfix/Dovecot/Postgres bu compose ile başlar — host’ta ayrı kurulum gerekmez.')

    tls_dir = Path(MAIL_TLS_MOUNT)
    try:
        material = ensure_mail_pki_files(
            tls_dir,
            mail_hostname=mail_hostname,
            mail_domain=domain,
            postfix_host=os.getenv('SMTP_HOST', 'postfix'),
            dovecot_host=os.getenv('IMAP_HOST', 'dovecot'),
        )
        messages.append(f'Mail TLS (PKI): {tls_dir}')
        pki_ca_pem = material.ca_cert_pem.decode('utf-8')
    except Exception as exc:
        logger.exception('compose PKI')
        return {
            'success': False,
            'error': f'Mail PKI hazırlanamadı: {exc}',
            'messages': messages,
        }

    ensure_runtime_mail_ca(pki_ca_pem)

    mail_cfg = {
        **config,
        'domain': domain,
        'mail_hostname': mail_hostname,
        'mail_pki_ca_pem': pki_ca_pem,
        'stack_already_provisioned': True,
    }
    mail_result = auto_setup_mail_services(mail_cfg, skip_busy_ports=True)
    messages.extend(mail_result.get('messages') or [])

    out: dict[str, Any] = {
        'success': bool(mail_result.get('success')),
        'messages': messages,
        'install_profile': 'compose_stack',
        'domain': domain,
        'mail_hostname': mail_hostname,
        'compose_stack': True,
        'mail': mail_result,
        'mail_endpoints': mail_result.get('mail_endpoints') or {},
        'smtp_ok': mail_result.get('smtp_ok'),
        'imap_ok': mail_result.get('imap_ok'),
    }
    if mail_result.get('success'):
        apply_mail_connectivity_to_system_config(mail_result)
        messages.append('Compose stack hazır — kurulum sihirbazına devam edebilirsiniz.')
    else:
        out['error'] = mail_result.get('error') or 'Mail TLS doğrulaması başarısız.'
    return out
