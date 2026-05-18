"""E-posta kimlik doğrulama başlıkları (SPF, DKIM, DMARC) ve Received zinciri."""
from __future__ import annotations

import re
from email.message import Message
from typing import Any

_AUTH_RE = re.compile(
    r'\b(spf|dkim|dmarc)\s*=\s*(pass|fail|softfail|neutral|none|temperror|permerror|bypass)',
    re.IGNORECASE,
)
_RECEIVED_FROM = re.compile(r'from\s+([^\s;(]+)', re.IGNORECASE)
_RECEIVED_BY = re.compile(r'by\s+([^\s;(]+)', re.IGNORECASE)


def _collect_header_text(msg: Message, name: str) -> str:
    parts = msg.get_all(name) or []
    return '\n'.join(str(p) for p in parts if p)


def _auth_status(combined: str, mechanism: str) -> str:
    mechanism = mechanism.lower()
    last = 'none'
    for m, status in _AUTH_RE.findall(combined):
        if m.lower() == mechanism:
            last = status.lower()
    return last


def _status_label(status: str) -> str:
    labels = {
        'pass': 'Geçti',
        'fail': 'Başarısız',
        'softfail': 'Zayıf başarısız',
        'neutral': 'Nötr',
        'none': 'Yok',
        'temperror': 'Geçici hata',
        'permerror': 'Kalıcı hata',
        'bypass': 'Atlandı',
    }
    return labels.get(status, status)


def _status_ok(status: str) -> bool | None:
    if status == 'pass':
        return True
    if status in ('fail', 'softfail', 'permerror'):
        return False
    return None


def parse_received_hops(msg: Message, *, limit: int = 6) -> list[dict[str, str]]:
    hops: list[dict[str, str]] = []
    for raw in (msg.get_all('Received') or [])[:limit]:
        text = str(raw).replace('\n', ' ').strip()
        from_m = _RECEIVED_FROM.search(text)
        by_m = _RECEIVED_BY.search(text)
        hops.append({
            'from': from_m.group(1) if from_m else '—',
            'by': by_m.group(1) if by_m else '—',
            'raw': text[:280],
        })
    return hops


def parse_mail_auth(msg: Message) -> dict[str, Any]:
    """SPF/DKIM/DMARC ve posta yolu özeti."""
    auth_parts = []
    for h in ('Authentication-Results', 'ARC-Authentication-Results', 'X-Authentication-Results'):
        block = _collect_header_text(msg, h)
        if block:
            auth_parts.append(block)
    received_spf = _collect_header_text(msg, 'Received-SPF')
    if received_spf:
        auth_parts.append(received_spf)
    combined = '\n'.join(auth_parts)

    spf = _auth_status(combined, 'spf')
    dkim = _auth_status(combined, 'dkim')
    dmarc = _auth_status(combined, 'dmarc')

    return {
        'spf': spf,
        'dkim': dkim,
        'dmarc': dmarc,
        'spf_label': _status_label(spf),
        'dkim_label': _status_label(dkim),
        'dmarc_label': _status_label(dmarc),
        'spf_ok': _status_ok(spf),
        'dkim_ok': _status_ok(dkim),
        'dmarc_ok': _status_ok(dmarc),
        'received_hops': parse_received_hops(msg),
        'message_id': (msg.get('Message-ID') or '').strip()[:512],
        'raw_auth': combined[:3000],
    }
