"""Arka plan AI görevleri için kısa süreli parola önbelleği (Redis)."""
from __future__ import annotations

import logging

import redis
from django.conf import settings

from jir_core.session_secrets import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)

_TTL = int(getattr(settings, 'WEBMAIL_CREDENTIAL_CACHE_TTL', 86400) or 86400)


def _redis():
    return redis.Redis.from_url(
        getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'),
        decode_responses=True,
    )


def _key(account_id: int) -> str:
    return f'webmail:cred:{account_id}'


def cache_account_password(account_id: int, password: str) -> None:
    if not account_id or not password:
        return
    try:
        _redis().setex(_key(account_id), _TTL, encrypt_secret(password))
    except Exception as exc:
        logger.debug('credential cache write failed: %s', exc)


def get_cached_account_password(account_id: int) -> str:
    try:
        token = _redis().get(_key(account_id))
        if not token:
            return ''
        return decrypt_secret(token)
    except Exception:
        return ''


def clear_cached_account_password(account_id: int) -> None:
    try:
        _redis().delete(_key(account_id))
    except Exception:
        pass
