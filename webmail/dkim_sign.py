"""Giden posta DKIM imzası — panelde üretilen anahtarlar (Postfix milter gerekmez)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


def _selector_from_domain(domain) -> str | None:
    rec = (getattr(domain, 'dkim_record', '') or '').strip()
    if not rec:
        return None
    m = re.match(r'^([a-zA-Z0-9._-]+)\._domainkey\.', rec)
    return m.group(1) if m else None


def sign_message_bytes(raw: bytes, account) -> bytes:
    """DKIM imzası ekle; anahtar yoksa mesajı olduğu gibi döndür."""
    try:
        domain = getattr(account, 'domain', None)
        if domain is None:
            return raw
        if not getattr(domain, 'dkim_enabled', False):
            return raw
        priv = (getattr(domain, 'dkim_private_key', '') or '').strip()
        if not priv:
            return raw
        selector = _selector_from_domain(domain)
        if not selector:
            return raw
        domain_name = (getattr(domain, 'name', '') or '').strip().lower()
        if not domain_name:
            return raw

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
        # RFC: DKIM-Signature ilk başlık olmalı
        if b'\r\n\r\n' in raw:
            head, body = raw.split(b'\r\n\r\n', 1)
            return head + b'\r\n' + sig + b'\r\n\r\n' + body
        return sig + raw
    except Exception as exc:
        logger.warning('DKIM imza atlandı (%s): %s', getattr(account, 'email', ''), exc)
        return raw
