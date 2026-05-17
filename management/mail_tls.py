"""Mail TLS politikası — uçtan uca şifreleme (iç PKI)."""
from __future__ import annotations

import logging
import os
import ssl
import tempfile
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

_CA_BOOTSTRAPPED: str | None = None


def mail_tls_mode() -> str:
    return (os.getenv('MAIL_TLS_MODE') or getattr(settings, 'MAIL_TLS_MODE', 'e2e')).strip().lower()


def mail_tls_e2e_required() -> bool:
    """İç ağda TLS zorunlu (varsayılan: evet). Yalnızca MAIL_TLS_MODE=off kapatır."""
    return mail_tls_mode() != 'off'


def smtp_starttls_required() -> bool:
    if os.getenv('SMTP_TLS_REQUIRED', '').strip():
        return os.getenv('SMTP_TLS_REQUIRED', '').lower() in ('1', 'true', 'yes')
    return mail_tls_e2e_required()


def imap_ssl_verify_required() -> bool:
    if os.getenv('IMAP_SSL_VERIFY', '').strip():
        return os.getenv('IMAP_SSL_VERIFY', '').lower() in ('1', 'true', 'yes')
    return mail_tls_e2e_required()


def _default_ca_paths() -> list[Path]:
    paths: list[Path] = []
    env_ca = (os.getenv('MAIL_TLS_CA_FILE') or getattr(settings, 'MAIL_TLS_CA_FILE', '') or '').strip()
    if env_ca:
        paths.append(Path(env_ca))
    paths.append(Path('/etc/jir-mail/tls/ca.crt'))
    paths.append(Path(tempfile.gettempdir()) / 'jir-mail-internal-ca.crt')
    return paths


def resolve_mail_tls_ca_file() -> str | None:
    """Doğrulama için güvenilir dahili CA dosyası."""
    global _CA_BOOTSTRAPPED
    if _CA_BOOTSTRAPPED and Path(_CA_BOOTSTRAPPED).is_file():
        return _CA_BOOTSTRAPPED

    for path in _default_ca_paths():
        if path.is_file():
            _CA_BOOTSTRAPPED = str(path)
            return _CA_BOOTSTRAPPED

    try:
        from installer.mail_connectivity import mail_endpoints_from_system_config

        ep = mail_endpoints_from_system_config()
        ca_pem = ep.get('tls_ca_pem')
        if isinstance(ca_pem, str) and 'BEGIN CERTIFICATE' in ca_pem:
            dest = Path(tempfile.gettempdir()) / 'jir-mail-internal-ca.crt'
            dest.write_text(ca_pem.strip() + '\n', encoding='utf-8')
            dest.chmod(0o644)
            _CA_BOOTSTRAPPED = str(dest)
            return _CA_BOOTSTRAPPED
    except Exception as exc:
        logger.debug('mail TLS CA SystemConfig: %s', exc)

    return None


def bootstrap_mail_tls_ca_from_db() -> None:
    """Uygulama başlangıcında CA'yı SystemConfig'ten diske yaz."""
    if not mail_tls_e2e_required():
        return
    resolve_mail_tls_ca_file()


def smtp_tls_context() -> ssl.SSLContext:
    if smtp_starttls_required():
        ca = resolve_mail_tls_ca_file()
        if not ca:
            raise ssl.SSLError(
                'SMTP TLS zorunlu ancak dahili CA bulunamadı. '
                'Kurulum sihirbazında mail adımını tamamlayın.'
            )
        ctx = ssl.create_default_context(cafile=ca)
        # İç DNS adı veya köprü IP ile bağlanılabilir; şifreleme + CA güveni yeterli.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def imap_tls_context() -> ssl.SSLContext | None:
    if not getattr(settings, 'IMAP_SSL', True):
        return None
    if imap_ssl_verify_required():
        ca = resolve_mail_tls_ca_file()
        if not ca:
            raise ssl.SSLError(
                'IMAP TLS doğrulaması zorunlu ancak dahili CA bulunamadı. '
                'Mail kurulum adımını çalıştırın.'
            )
        ctx = ssl.create_default_context(cafile=ca)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def verify_smtp_starttls(host: str, port: int, *, timeout: float = 5.0) -> bool:
    """Submission portunda STARTTLS + CA doğrulaması."""
    import smtplib

    if not smtp_starttls_required():
        return True
    try:
        ctx = smtp_tls_context()
        with smtplib.SMTP(host, port, timeout=timeout) as smtp:
            smtp.ehlo()
            if not smtp.has_extn('starttls'):
                return False
            smtp.starttls(context=ctx)
            smtp.ehlo()
        return True
    except Exception as exc:
        logger.debug('SMTP STARTTLS verify %s:%s: %s', host, port, exc)
        return False


def verify_imap_tls(host: str, port: int, *, timeout: float = 5.0) -> bool:
    from imapclient import IMAPClient

    if not imap_ssl_verify_required():
        return True
    try:
        ctx = imap_tls_context()
        with IMAPClient(host, port=port, ssl=True, ssl_context=ctx, timeout=timeout) as _:
            return True
    except Exception as exc:
        logger.debug('IMAP TLS verify %s:%s: %s', host, port, exc)
        return False
