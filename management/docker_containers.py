"""
Docker servis konteyner adları: SystemConfig.docker_container_map (kalıcı)
üzerinden gerçek adlar; yoksa Django settings (env), yoksa jir_* varsayılanları.
"""
from __future__ import annotations

import logging
import os
from typing import Dict, FrozenSet

from django.conf import settings

from saas.models import SystemConfig

logger = logging.getLogger(__name__)

SERVICE_KEYS = ('postgres', 'postfix', 'dovecot', 'redis', 'django', 'celery', 'celery_beat')

_DISPLAY_TO_SERVICE_KEY = {
    'PostgreSQL': 'postgres',
    'Postfix': 'postfix',
    'Dovecot': 'dovecot',
    'Redis': 'redis',
}

_SETTINGS_ATTR = {
    'postgres': 'JIR_CONTAINER_POSTGRES',
    'postfix': 'JIR_CONTAINER_POSTFIX',
    'dovecot': 'JIR_CONTAINER_DOVECOT',
    'redis': 'JIR_CONTAINER_REDIS',
    'django': 'JIR_CONTAINER_DJANGO',
    'celery': 'JIR_CONTAINER_CELERY',
    'celery_beat': 'JIR_CONTAINER_CELERY_BEAT',
}

_DEFAULT_JIR = {
    'postgres': 'jir_postgres',
    'postfix': 'jir_postfix',
    'dovecot': 'jir_dovecot',
    'redis': 'jir_redis',
    'django': 'jir_django',
    'celery': 'jir_celery',
    'celery_beat': 'jir_celery_beat',
}

# os.environ içinde anahtar varsa (Coolify / .env) — DB otomatik keşfinden önce gelir
_ENV_KEY_FOR_SERVICE = {
    'postgres': 'JIR_CONTAINER_POSTGRES',
    'postfix': 'JIR_CONTAINER_POSTFIX',
    'dovecot': 'JIR_CONTAINER_DOVECOT',
    'redis': 'JIR_CONTAINER_REDIS',
    'django': 'JIR_CONTAINER_DJANGO',
    'celery': 'JIR_CONTAINER_CELERY',
    'celery_beat': 'JIR_CONTAINER_CELERY_BEAT',
}


def _normalize(name: str) -> str:
    if not name:
        return ''
    return str(name).strip().strip('/')


def read_stored_container_map() -> Dict[str, str]:
    try:
        conf = SystemConfig.objects.only('docker_container_map').first()
        if not conf or not conf.docker_container_map:
            return {}
        raw = conf.docker_container_map
        if not isinstance(raw, dict):
            return {}
        return {
            str(k).strip(): _normalize(str(v))
            for k, v in raw.items()
            if k and v and str(v).strip()
        }
    except Exception as exc:
        logger.debug('docker_container_map okunamadı: %s', exc)
        return {}


def merged_container_name(service_key: str) -> str:
    """Çözüm sırası: 1) Ortamda açıkça JIR_CONTAINER_* (os.environ), 2) DB keşfi, 3) Django settings."""
    sk = (service_key or '').strip().lower()
    env_k = _ENV_KEY_FOR_SERVICE.get(sk)
    if env_k and env_k in os.environ:
        raw = (os.environ.get(env_k) or '').strip()
        if raw:
            return _normalize(raw)

    stored = read_stored_container_map().get(sk, '')
    if stored:
        return stored

    attr = _SETTINGS_ATTR.get(sk)
    if attr:
        v = getattr(settings, attr, None)
        if v and str(v).strip():
            return _normalize(str(v))
    return _DEFAULT_JIR.get(sk, '')


def all_resolved_container_names() -> FrozenSet[str]:
    """İzin listesi: tüm servislerin birleşik adları + DB’deki ekstra değerler."""
    names = set(read_stored_container_map().values())
    for sk in SERVICE_KEYS:
        n = merged_container_name(sk)
        if n:
            names.add(n)
    return frozenset(names)


def persist_container_alias(service_key: str, physical_name: str) -> None:
    """Keşfedilen gerçek adı kalıcı kaydet (jir_* yerine). Ortamda JIR_CONTAINER_* sabitlendiyse ezme."""
    sk = (service_key or '').strip().lower()
    pn = _normalize(physical_name)
    if not sk or not pn:
        return
    env_k = _ENV_KEY_FOR_SERVICE.get(sk)
    if env_k and env_k in os.environ and (os.environ.get(env_k) or '').strip():
        return
    try:
        conf = SystemConfig.objects.first()
        if not conf:
            return
        m = dict(conf.docker_container_map or {})
        if not isinstance(m, dict):
            m = {}
        if m.get(sk) == pn:
            return
        m[sk] = pn
        conf.docker_container_map = m
        conf.save(update_fields=['docker_container_map', 'updated_at'])
        logger.info('docker_container_map güncellendi: %s -> %s', sk, pn)
    except Exception as exc:
        logger.warning('docker_container_map kaydedilemedi: %s', exc)


def service_key_from_container_url_segment(lk: str) -> str | None:
    """URL veya UI segmenti → postgres | postfix | …"""
    k = (lk or '').strip().lower()
    m = {
        'postgresql': 'postgres',
        'postgres': 'postgres',
        'jir_postgres': 'postgres',
        'postfix': 'postfix',
        'jir_postfix': 'postfix',
        'dovecot': 'dovecot',
        'jir_dovecot': 'dovecot',
        'redis': 'redis',
        'jir_redis': 'redis',
        'django': 'django',
        'jir_django': 'django',
        'celery': 'celery',
        'jir_celery': 'celery',
        'celery_beat': 'celery_beat',
        'jir_celery_beat': 'celery_beat',
    }
    return m.get(k)


def service_key_for_display_name(display_name: str) -> str | None:
    return _DISPLAY_TO_SERVICE_KEY.get(display_name or '')
