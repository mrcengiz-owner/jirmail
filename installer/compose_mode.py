"""Compose deploy algılama — döngüsel import yok (mail_connectivity ↔ compose_stack)."""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def is_compose_stack() -> bool:
    """Docker Compose ile deploy: ayrı Docker API kurulumu yok."""
    flag = os.getenv('JIR_COMPOSE_STACK', '').strip().lower()
    if flag in ('1', 'true', 'yes', 'on'):
        return True
    if flag in ('0', 'false', 'no', 'off'):
        return False
    smtp = os.getenv('SMTP_HOST', '').strip()
    imap = os.getenv('IMAP_HOST', '').strip()
    return smtp in ('postfix', 'jir_postfix') and imap in ('dovecot', 'jir_dovecot')


def ensure_runtime_mail_ca(ca_pem: str | bytes | None) -> None:
    """Doğrulama öncesi dahili CA'yı panel sürecinde /tmp'ye yaz."""
    if not ca_pem:
        return
    try:
        from installer.mail_pki import write_ca_to_path

        raw = ca_pem.encode('utf-8') if isinstance(ca_pem, str) else ca_pem
        if b'BEGIN CERTIFICATE' not in raw:
            return
        dest = Path(tempfile.gettempdir()) / 'jir-mail-internal-ca.crt'
        write_ca_to_path(raw, dest)
        os.environ['MAIL_TLS_CA_FILE'] = str(dest)
    except Exception as exc:
        logger.debug('runtime mail CA: %s', exc)
