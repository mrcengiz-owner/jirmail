"""Giden posta DKIM imzası — panelde üretilen anahtarlar (Postfix milter gerekmez)."""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


def _selector_from_domain(domain) -> str | None:
    rec = (getattr(domain, 'dkim_record', '') or '').strip()
    if not rec:
        return None
    m = re.match(r'^([a-zA-Z0-9._-]+)\._domainkey\.', rec)
    return m.group(1) if m else None


def dkim_sign_status(account) -> dict[str, Any]:
    """Domain DKIM yapılandırma durumu."""
    domain = getattr(account, 'domain', None)
    if domain is None:
        return {'configured': False, 'enabled': False, 'reason': 'Hesap domain kaydı yok'}
    enabled = bool(getattr(domain, 'dkim_enabled', False))
    priv = bool((getattr(domain, 'dkim_private_key', '') or '').strip())
    selector = _selector_from_domain(domain)
    verified = getattr(domain, 'verification_status', '') == 'verified'
    return {
        'configured': enabled and priv and bool(selector),
        'enabled': enabled,
        'verified_dns': verified,
        'selector': selector or '',
        'domain': getattr(domain, 'name', '') or '',
    }


def sign_message_bytes(raw: bytes, account) -> tuple[bytes, dict[str, Any]]:
    """DKIM imzası ekle. (mesaj_bytes, durum) döner."""
    status: dict[str, Any] = {
        'signed': False,
        'required': False,
        'reason': '',
    }
    meta = dkim_sign_status(account)
    status['required'] = meta.get('configured', False)
    status['verified_dns'] = meta.get('verified_dns', False)

    if not meta.get('configured'):
        status['reason'] = meta.get('reason') or 'DKIM yapılandırılmamış'
        return raw, status

    try:
        domain = account.domain
        priv = (domain.dkim_private_key or '').strip()
        selector = meta['selector']
        domain_name = (domain.name or '').strip().lower()

        import dkim

        sig = dkim.sign(
            raw,
            selector.encode(),
            domain_name.encode(),
            priv.encode() if isinstance(priv, str) else priv,
            include_headers=[
                b'From',
                b'To',
                b'Cc',
                b'Subject',
                b'Message-ID',
                b'Date',
                b'MIME-Version',
                b'Content-Type',
            ],
        )
        if b'\r\n\r\n' in raw:
            head, body = raw.split(b'\r\n\r\n', 1)
            signed = head + b'\r\n' + sig + b'\r\n\r\n' + body
        else:
            signed = sig + raw

        if b'DKIM-Signature:' not in signed and b'dkim-signature:' not in signed.lower():
            status['reason'] = 'İmza üretildi ama mesaja eklenemedi'
            logger.error('DKIM imza eklenemedi: %s', account.email)
            return raw, status

        status['signed'] = True
        logger.info('DKIM imzalandı: %s (selector=%s)', account.email, selector)
        return signed, status
    except Exception as exc:
        status['reason'] = str(exc)
        logger.error('DKIM imza hatası (%s): %s', getattr(account, 'email', ''), exc)
        return raw, status
