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
VOLUME_CA_PATH = Path('/etc/jir-mail/tls/ca.crt')


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


def invalidate_mail_tls_ca_cache() -> None:
    """CA yolu değiştiğinde veya PKI yenilendiğinde önbelleği temizle."""
    global _CA_BOOTSTRAPPED
    _CA_BOOTSTRAPPED = None


def _default_ca_paths() -> list[Path]:
    """Öncelik: volume CA (Postfix ile aynı) → env → tempfile."""
    paths: list[Path] = []
    # Volume her zaman en güvenilir kaynak — Postfix/Dovecot ile paylaşılır
    if VOLUME_CA_PATH.is_file():
        paths.append(VOLUME_CA_PATH)

    env_ca = (os.getenv('MAIL_TLS_CA_FILE') or getattr(settings, 'MAIL_TLS_CA_FILE', '') or '').strip()
    if env_ca:
        env_path = Path(env_ca)
        if env_path != VOLUME_CA_PATH:
            paths.append(env_path)

    paths.append(Path(tempfile.gettempdir()) / 'jir-mail-internal-ca.crt')
    # Tekrarları kaldır, sırayı koru
    seen: set[str] = set()
    out: list[Path] = []
    for p in paths:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def resolve_mail_tls_ca_file() -> str | None:
    """Doğrulama için güvenilir dahili CA dosyası."""
    global _CA_BOOTSTRAPPED

    # Volume CA varsa cache'lenmiş /tmp yolunu ezer (eski SystemConfig PEM tuzağı)
    if VOLUME_CA_PATH.is_file() and VOLUME_CA_PATH.stat().st_size > 0:
        vol = str(VOLUME_CA_PATH)
        if _CA_BOOTSTRAPPED != vol:
            _CA_BOOTSTRAPPED = vol
            os.environ['MAIL_TLS_CA_FILE'] = vol
        return _CA_BOOTSTRAPPED

    if _CA_BOOTSTRAPPED and Path(_CA_BOOTSTRAPPED).is_file():
        return _CA_BOOTSTRAPPED

    for path in _default_ca_paths():
        if path.is_file() and path.stat().st_size > 0:
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


def heal_mail_tls_pki(*, force_regen: bool = False) -> dict:
    """Bozuk / uyumsuz dahili PKI'yi onar; Postfix/Dovecot TLS'i yenile."""
    import time

    out: dict = {'ok': False, 'actions': []}
    try:
        from installer.mail_pki import MAIL_TLS_MOUNT, ensure_mail_pki_files, mail_pki_chain_ok

        domain = (os.getenv('MAIL_DOMAIN') or getattr(settings, 'MAIL_DOMAIN', None) or 'mail.local').strip()
        hostname = (
            os.getenv('MAIL_HOSTNAME')
            or getattr(settings, 'MAIL_SERVER_HOSTNAME', None)
            or f'mail.{domain}'
        ).strip()
        tls_dir = Path(MAIL_TLS_MOUNT)
        material = ensure_mail_pki_files(
            tls_dir,
            mail_hostname=hostname,
            mail_domain=domain,
            postfix_host=os.getenv('SMTP_HOST', 'postfix'),
            dovecot_host=os.getenv('IMAP_HOST', 'dovecot'),
            force=force_regen,
        )
        chain_ok = mail_pki_chain_ok(material)
        out['actions'].append({'action': 'ensure_pki', 'chain_ok': chain_ok, 'force': force_regen})
        if not chain_ok and not force_regen:
            material = ensure_mail_pki_files(
                tls_dir,
                mail_hostname=hostname,
                mail_domain=domain,
                postfix_host=os.getenv('SMTP_HOST', 'postfix'),
                dovecot_host=os.getenv('IMAP_HOST', 'dovecot'),
                force=True,
            )
            out['actions'].append({'action': 'force_regen', 'chain_ok': mail_pki_chain_ok(material)})

        invalidate_mail_tls_ca_cache()
        if VOLUME_CA_PATH.is_file():
            os.environ['MAIL_TLS_CA_FILE'] = str(VOLUME_CA_PATH)
        resolve_mail_tls_ca_file()
        out['actions'].append({'action': 'ca_cache_reset', 'ca': resolve_mail_tls_ca_file()})

        # Postfix/Dovecot bellekteki eski sertifikayı bıraksın
        try:
            from management.mail_stack_health import _docker_client, _dovecot_container_name, _postfix_container_name

            client = _docker_client()
            for name, cmd in (
                (_postfix_container_name(), ['postfix', 'reload']),
                (_dovecot_container_name(), ['doveadm', 'reload']),
            ):
                try:
                    c = client.containers.get(name)
                    code, _logs = c.exec_run(cmd)
                    out['actions'].append({'action': 'reload', 'container': name, 'exit': code})
                    if code != 0:
                        c.restart(timeout=20)
                        out['actions'].append({'action': 'restart', 'container': name})
                except Exception as exc:
                    out['actions'].append({'action': 'reload_failed', 'container': name, 'error': str(exc)})
            client.close()
            time.sleep(2)
        except Exception as exc:
            out['actions'].append({'action': 'reload_skip', 'error': str(exc)})

        out['ok'] = True
    except Exception as exc:
        out['error'] = str(exc)
        logger.warning('heal_mail_tls_pki: %s', exc)
    return out


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


def verify_imap_tls(
    host: str,
    port: int,
    *,
    timeout: float = 5.0,
    log_failure: bool = False,
) -> bool:
    """IMAPS: TLS el sıkışması + Dovecot * OK satırı (IMAPClient bazen Broken pipe verir)."""
    import socket
    import time

    if not imap_ssl_verify_required():
        return True
    try:
        ctx = imap_tls_context()
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with ctx.wrap_socket(raw, server_hostname=host) as tls:
                tls.settimeout(timeout)
                buf = b''
                deadline = time.monotonic() + min(timeout, 8.0)
                while len(buf) < 4096 and b'\n' not in buf:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            'IMAP * OK gelmedi (Dovecot auth çöküyor olabilir; '
                            'docker logs jir_dovecot | tail -20)'
                        )
                    tls.settimeout(max(0.5, deadline - time.monotonic()))
                    chunk = tls.recv(512)
                    if not chunk:
                        break
                    buf += chunk
                if not buf.startswith(b'* OK'):
                    raise ssl.SSLError(f'IMAP greeting beklenmiyor: {buf[:120]!r}')
        return True
    except Exception as exc:
        msg = f'IMAP TLS verify {host}:{port}: {exc}'
        if log_failure:
            logger.warning(msg)
        else:
            logger.debug(msg)
        return False
