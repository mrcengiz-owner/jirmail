"""Giriş brute-force koruması (IP + e-posta)."""
from __future__ import annotations

import hashlib

from django.core.cache import cache


MAX_FAILURES = 8
WINDOW_SECONDS = 900  # 15 dk
LOCK_SECONDS = 900


def _key(kind: str, value: str) -> str:
    digest = hashlib.sha256(value.encode('utf-8')).hexdigest()[:32]
    return f'jir_login:{kind}:{digest}'


def client_ip(request) -> str:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    if forwarded:
        return forwarded
    return request.META.get('REMOTE_ADDR') or 'unknown'


def login_blocked(request, email: str) -> str | None:
    """Engelli ise kullanıcı mesajı döner."""
    email_n = (email or '').strip().lower()
    ip = client_ip(request)
    for kind, value in (('ip', ip), ('email', email_n)):
        if cache.get(_key(f'lock:{kind}', value)):
            return 'Çok fazla başarısız deneme. Lütfen 15 dakika sonra tekrar deneyin.'
    return None


def record_login_failure(request, email: str) -> None:
    email_n = (email or '').strip().lower()
    ip = client_ip(request)
    for kind, value in (('ip', ip), ('email', email_n)):
        if not value:
            continue
        fail_key = _key(f'fail:{kind}', value)
        count = int(cache.get(fail_key) or 0) + 1
        cache.set(fail_key, count, WINDOW_SECONDS)
        if count >= MAX_FAILURES:
            cache.set(_key(f'lock:{kind}', value), 1, LOCK_SECONDS)


def clear_login_failures(request, email: str) -> None:
    email_n = (email or '').strip().lower()
    ip = client_ip(request)
    for kind, value in (('ip', ip), ('email', email_n)):
        if not value:
            continue
        cache.delete(_key(f'fail:{kind}', value))
        cache.delete(_key(f'lock:{kind}', value))
