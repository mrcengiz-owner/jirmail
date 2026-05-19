"""Alıcı adresi ayrıştırma ve doğrulama."""
from __future__ import annotations

import re
from email.utils import getaddresses

_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def parse_recipient_list(raw: str | None) -> list[str]:
    """Virgülle ayrılmış alıcıları geçerli e-posta adreslerine çevirir.

    'CC', boş veya @ içermeyen girdiler atlanır (Postfix bunları
    CC@myhostname olarak genişletir → teslim hatası).
    """
    if not raw or not str(raw).strip():
        return []
    seen: set[str] = set()
    out: list[str] = []
    for _name, addr in getaddresses([str(raw)]):
        email = (addr or '').strip().lower()
        if not email or '@' not in email:
            continue
        if not _EMAIL_RE.match(email):
            continue
        if email in seen:
            continue
        seen.add(email)
        out.append(email)
    return out
