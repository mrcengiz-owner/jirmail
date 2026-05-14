"""Mail reputation — gönderilen/teslim/bounce istatistiği.

Postfix mail.log'unu parse edip son 24h / 7d istatistik üretir.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from .postfix_inspector import _exec


LOG_PATHS = ['/var/log/mail.log', '/var/log/maillog']


def _read_log(lines: int = 5000) -> str:
    for path in LOG_PATHS:
        code, out = _exec(['sh', '-c', f'test -f {path} && tail -n {lines} {path}'])
        if code == 0 and out:
            return out
    return ''


_SENT_RE = re.compile(r'status=sent')
_BOUNCED_RE = re.compile(r'status=bounced')
_DEFERRED_RE = re.compile(r'status=deferred')
_REJECT_RE = re.compile(r'NOQUEUE: reject|reject:')
_TIMESTAMP_RE = re.compile(r'^(\w{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})')


def compute_stats(*, window_hours: int = 24) -> dict:
    """Son <window_hours> içindeki sent/bounced/deferred/rejected sayısını hesapla."""
    log = _read_log(lines=10000)
    if not log:
        return {'sent': 0, 'bounced': 0, 'deferred': 0, 'rejected': 0, 'total': 0, 'available': False}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cutoff = now - timedelta(hours=window_hours)

    sent = bounced = deferred = rejected = 0
    for line in log.splitlines():
        ts_match = _TIMESTAMP_RE.match(line)
        if ts_match:
            try:
                ts = datetime.strptime(f'{now.year} {ts_match.group(1)}', '%Y %b %d %H:%M:%S')
                if ts > now:
                    ts = ts.replace(year=now.year - 1)
                if ts < cutoff:
                    continue
            except Exception:
                pass

        if _SENT_RE.search(line):
            sent += 1
        elif _BOUNCED_RE.search(line):
            bounced += 1
        elif _DEFERRED_RE.search(line):
            deferred += 1
        elif _REJECT_RE.search(line):
            rejected += 1

    total = sent + bounced + deferred + rejected
    delivery_rate = (sent / total * 100.0) if total else 0.0

    return {
        'window_hours': window_hours,
        'sent': sent,
        'bounced': bounced,
        'deferred': deferred,
        'rejected': rejected,
        'total': total,
        'delivery_rate_percent': round(delivery_rate, 2),
        'available': True,
    }
