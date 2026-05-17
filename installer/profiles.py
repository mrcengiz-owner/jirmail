"""Kurulum profilleri — tek kaynak (canonical id + alias + UI meta).

Yürütme yolu yalnızca üç profildir; Coolify / Dokploy vb. kullanıcı etiketleri
aynı yola normalize edilir (orchestrator ile uyumlu).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROFILE_DOCKER_STACK = 'docker_stack'
PROFILE_PLATFORM_ENV = 'platform_env'
PROFILE_PLATFORM_MANUAL = 'platform_manual'

CANONICAL_PROFILES = frozenset({
    PROFILE_DOCKER_STACK,
    PROFILE_PLATFORM_ENV,
    PROFILE_PLATFORM_MANUAL,
})

# API / env üzerinden gelebilecek eş anlamlılar → canonical
PROFILE_ALIASES: Dict[str, str] = {
    # PaaS / konteyner platformları (DATABASE_URL veya manuel DB)
    'coolify': PROFILE_PLATFORM_ENV,
    'dokploy': PROFILE_PLATFORM_ENV,
    'railway': PROFILE_PLATFORM_ENV,
    'render': PROFILE_PLATFORM_ENV,
    'fly': PROFILE_PLATFORM_ENV,
    'fly_io': PROFILE_PLATFORM_ENV,
    'platform': PROFILE_PLATFORM_ENV,
    'managed': PROFILE_PLATFORM_ENV,
    'env_db': PROFILE_PLATFORM_ENV,
    'database_url': PROFILE_PLATFORM_ENV,
    # Paylaşımlı / harici Postgres
    'cpanel': PROFILE_PLATFORM_MANUAL,
    'plesk': PROFILE_PLATFORM_MANUAL,
    'shared_hosting': PROFILE_PLATFORM_MANUAL,
    'external_postgres': PROFILE_PLATFORM_MANUAL,
    'manual': PROFILE_PLATFORM_MANUAL,
    'manual_postgres': PROFILE_PLATFORM_MANUAL,
    # Tam stack
    'compose': PROFILE_DOCKER_STACK,
    'docker': PROFILE_DOCKER_STACK,
    'full_stack': PROFILE_DOCKER_STACK,
}


def normalize_install_profile(raw: Optional[str]) -> str:
    """Bilinmeyen veya boş değerlerde açık hata; alias → canonical."""
    if raw is None:
        raise ValueError('install_profile zorunludur.')
    key = str(raw).strip().lower()
    if not key:
        raise ValueError('install_profile boş olamaz.')
    if key in PROFILE_ALIASES:
        return PROFILE_ALIASES[key]
    if key in CANONICAL_PROFILES:
        return key
    allowed = ', '.join(sorted(CANONICAL_PROFILES | set(PROFILE_ALIASES.keys())))
    raise ValueError(f'Bilinmeyen kurulum profili: {raw!r}. Geçerli örnekler: {allowed}')


def probe_capabilities() -> Dict[str, Any]:
    """Bootstrap için: Docker API ve DATABASE_URL varlığı (ping ile)."""
    from django.conf import settings

    from installer.compose_mode import is_compose_stack
    from installer.db_url import has_database_url as _has_db_url

    if is_compose_stack():
        return {
            'docker_available': False,
            'has_database_url': _has_db_url(),
            'managed_install_forced': False,
            'compose_stack': True,
        }

    has_database_url = _has_db_url()
    docker_available = False
    if os.getenv('JIR_MANAGED_INSTALL', '').lower() in ('1', 'true', 'yes'):
        return {
            'docker_available': False,
            'has_database_url': has_database_url,
            'managed_install_forced': True,
        }

    docker_host = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    if docker_host.startswith('unix://'):
        path = docker_host[len('unix://') :]
        if path.startswith('//'):
            path = path[1:]
        path = path or '/var/run/docker.sock'
        if not os.path.exists(path):
            return {
                'docker_available': False,
                'has_database_url': has_database_url,
                'managed_install_forced': False,
            }

    try:
        import docker

        client = docker.DockerClient(base_url=docker_host, timeout=5)
        client.ping()
        client.close()
        docker_available = True
    except Exception as exc:
        logger.debug('Docker probe başarısız: %s', exc)

    return {
        'docker_available': docker_available,
        'has_database_url': has_database_url,
        'managed_install_forced': False,
    }


def suggested_profile_from_capabilities(cap: Dict[str, Any]) -> str:
    """Tek sunucu: Compose veya Docker API stack."""
    if cap.get('compose_stack'):
        return 'compose_stack'
    if cap.get('docker_available'):
        return PROFILE_DOCKER_STACK
    if cap.get('has_database_url'):
        return PROFILE_PLATFORM_ENV
    return PROFILE_PLATFORM_MANUAL


def install_modes_for_ui(cap: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Sihirbaz kartları — her biri canonical `id` ile."""
    compose_ok = bool(cap.get('compose_stack'))
    docker_ok = bool(cap.get('docker_available'))
    db_url = bool(cap.get('has_database_url'))
    forced = bool(cap.get('managed_install_forced'))

    modes: List[Dict[str, Any]] = [
        {
            'id': 'compose_stack',
            'title': 'Docker Compose (önerilen)',
            'subtitle': 'Panel, Postgres, Redis, Postfix ve Dovecot aynı stack — host’ta ek kurulum yok.',
            'scenarios': 'Coolify “Docker Compose”, VPS `docker compose up`, tek komut.',
            'disabled': not compose_ok,
            'recommended': compose_ok,
            'disabled_reason': (
                None
                if compose_ok
                else 'JIR_COMPOSE_STACK=1 ve SMTP_HOST/IMAP_HOST compose servis adları gerekir.'
            ),
        },
        {
            'id': PROFILE_DOCKER_STACK,
            'title': 'Docker API ile kurulum',
            'subtitle': 'PostgreSQL, Redis, Postfix, Dovecot bu API üzerinden ayağa kalkar.',
            'scenarios': 'Kendi VPS, docker compose, Docker soketi erişimi olan PaaS.',
            'disabled': not docker_ok or compose_ok,
            'recommended': docker_ok and not compose_ok,
            'disabled_reason': (
                None
                if docker_ok
                else (
                    'JIR_MANAGED_INSTALL=1: Docker orkestrasyonu bilinçli olarak kapalı.'
                    if forced
                    else (
                        'Bu mod kurulum sırasında sunucuya Docker ile konteyner açmak için Docker API gerektirir. '
                        'Coolify’da uygulama servisinizde /var/run/docker.sock genelde yoktur → bu seçenek kilitlenir. '
                        'Çözüm: (1) Coolify Service → Volume: host /var/run/docker.sock → container /var/run/docker.sock '
                        '(yalnız güvendiğiniz sunucuda; güvenlik riskidir), veya (2) “Ortam veritabanı” + Postgres/mail için '
                        'ayrı Coolify Compose veya Dockerfile stack kullanın.'
                    )
                )
            ),
        },
        {
            'id': PROFILE_PLATFORM_ENV,
            'title': 'Ortam veritabanı (DATABASE_URL)',
            'subtitle': 'Sunucuda tanımlı DATABASE_URL ile migrate; mail servisleri platformda ayrı.',
            'scenarios': 'Coolify, Dokploy, Railway, Render vb. — Postgres servisi uygulamaya bağlı.',
            'disabled': not db_url or docker_ok,
            'disabled_reason': (
                'Tek sunucu kurulumu: Docker erişimi varsa tam stack kullanılır.'
                if docker_ok
                else (
                    'DATABASE_URL tanımlı değil. Platformda PostgreSQL ekleyip uygulama ortamına bağlayın.'
                    if not db_url
                    else None
                )
            ),
        },
        {
            'id': PROFILE_PLATFORM_MANUAL,
            'title': 'Manuel PostgreSQL',
            'subtitle': 'Host, veritabanı, kullanıcı ve şifre ile migrate; uygulamanın DB’si aynı hedefe işaret etmeli.',
            'scenarios': 'cPanel, Plesk, harici RDS veya Coolify’da URL henüz yokken geçici bağlantı.',
            'disabled': docker_ok,
            'disabled_reason': (
                'Tek sunucu kurulumu: Docker ile tam stack önerilir.'
                if docker_ok
                else None
            ),
        },
    ]
    return modes


def validate_manual_db_connection(dbm: Dict[str, Any]) -> tuple[bool, str]:
    """Kurulum başlatmadan önce manuel PostgreSQL doğrulaması."""
    try:
        import psycopg2
    except ImportError:
        return False, 'psycopg2 kurulu değil.'

    host = (dbm.get('host') or '').strip()
    name = (dbm.get('name') or '').strip()
    user = (dbm.get('user') or '').strip()
    port = int(dbm.get('port') or 5432)
    password = str(dbm.get('password') or '')

    if not (host and name and user):
        return False, 'Manuel veritabanı: sunucu, veritabanı adı ve kullanıcı zorunludur.'

    try:
        conn = psycopg2.connect(
            host=host,
            port=port,
            dbname=name,
            user=user,
            password=password,
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
        return True, 'Bağlantı başarılı.'
    except Exception as exc:
        return False, str(exc)
