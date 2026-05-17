"""Tek sunucu — sihirbaz açılışında Docker stack + mail TLS bootstrap."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from django.conf import settings

from installer.db_url import has_database_url, resolve_database_url
from installer.mail_connectivity import auto_setup_mail_services, apply_mail_connectivity_to_system_config
from installer.profiles import PROFILE_DOCKER_STACK, PROFILE_PLATFORM_ENV

logger = logging.getLogger(__name__)


def discover_stack_paths() -> dict[str, Any]:
    """Repo / konteyner içi gerekli dizinleri doğrula."""
    base = Path(settings.BASE_DIR).resolve()
    dovecot_df = base / 'dovecot' / 'Dockerfile'
    manage_py = base / 'manage.py'
    return {
        'base_dir': str(base),
        'dovecot_dockerfile': str(dovecot_df),
        'manage_py': str(manage_py),
        'dovecot_ok': dovecot_df.is_file(),
        'manage_ok': manage_py.is_file(),
        'in_docker': bool(getattr(settings, 'IN_DOCKER', False)),
    }


def _effective_profile(config: dict[str, Any], docker_available: bool) -> str:
    """Tek sunucu: Docker varsa her zaman tam stack."""
    raw = (config.get('install_profile') or '').strip()
    if docker_available:
        return PROFILE_DOCKER_STACK
    if raw in (PROFILE_PLATFORM_ENV, 'platform_env'):
        return PROFILE_PLATFORM_ENV
    return raw or PROFILE_DOCKER_STACK


def _apply_internal_database_url(config: dict[str, Any]) -> str | None:
    """docker_stack sonrası Django/migrate için DATABASE_URL."""
    if config.get('install_profile') != PROFILE_DOCKER_STACK:
        return None
    pw = str(config.get('postgres_password') or '')
    if not pw:
        return None
    user = quote_plus(str(config.get('postgres_user') or 'postgres'))
    password = quote_plus(pw)
    db = str(config.get('postgres_db') or 'jir_mail_prod').lstrip('/')
    host = str(config.get('postgres_host') or 'jir_postgres')
    port = int(config.get('postgres_port') or 5432)
    url = f'postgresql://{user}:{password}@{host}:{port}/{db}'
    os.environ['DATABASE_URL'] = url
    return url


def bootstrap_single_server(
    config: dict[str, Any],
    *,
    docker_client: Any | None = None,
) -> dict[str, Any]:
    """Sihirbaz başlangıcı: dizinleri bul, konteynerleri oluştur, mail TLS doğrula."""
    from installer.orchestrator import _get_docker_client_optional, provision_docker_stack_sync

    messages: list[str] = []
    paths = discover_stack_paths()
    messages.append(f"Proje kökü: {paths['base_dir']}")

    if not paths['dovecot_ok']:
        return {
            'success': False,
            'error': f"dovecot/Dockerfile bulunamadı: {paths['dovecot_dockerfile']}",
            'paths': paths,
            'messages': messages,
        }

    client = docker_client or _get_docker_client_optional()
    if client is None:
        return {
            'success': False,
            'error': (
                'Docker API erişilemiyor. Tek sunucu kurulumu için panel konteynerine '
                '/var/run/docker.sock mount edilmelidir.'
            ),
            'paths': paths,
            'messages': messages,
            'docker_available': False,
        }

    domain = (config.get('domain') or os.getenv('MAIL_DOMAIN') or '').strip() or 'mail.local'
    mail_hostname = (config.get('mail_hostname') or f'mail.{domain}').strip()
    profile = _effective_profile(config, docker_available=True)
    config = {
        **config,
        'domain': domain,
        'mail_hostname': mail_hostname,
        'install_profile': profile,
    }
    messages.append(f'Kurulum profili (tek sunucu): {profile}')
    messages.append(f'Mail domain: {domain}')

    try:
        if profile == PROFILE_DOCKER_STACK:
            stack_msgs = provision_docker_stack_sync(client, config)
            messages.extend(stack_msgs)
            if config.get('mail_pki_ca_pem'):
                messages.append('Mail PKI tamam (docker_stack).')
            db_url = _apply_internal_database_url(config)
            if db_url:
                messages.append('DATABASE_URL → jir_postgres (iç ağ) ayarlandı.')
        else:
            messages.append('Harici veritabanı — yalnızca mail konteynerleri kurulacak.')
            if not has_database_url():
                return {
                    'success': False,
                    'error': 'PostgreSQL bağlantısı yok (DATABASE_URL veya Django DATABASES).',
                    'paths': paths,
                    'messages': messages,
                }
            try:
                resolve_database_url()
            except Exception as exc:
                return {
                    'success': False,
                    'error': str(exc),
                    'paths': paths,
                    'messages': messages,
                }

        mail_result = auto_setup_mail_services(
            config,
            docker_client=client,
            skip_busy_ports=bool(config.get('stack_skip_busy_host_ports', True)),
        )
        messages.extend(mail_result.get('messages') or [])

        out: dict[str, Any] = {
            'success': bool(mail_result.get('success')),
            'paths': paths,
            'messages': messages,
            'install_profile': profile,
            'domain': domain,
            'mail_hostname': mail_hostname,
            'docker_available': True,
            'mail': mail_result,
            'mail_endpoints': mail_result.get('mail_endpoints') or {},
            'smtp_ok': mail_result.get('smtp_ok'),
            'imap_ok': mail_result.get('imap_ok'),
        }
        if mail_result.get('success'):
            apply_mail_connectivity_to_system_config(mail_result)
        else:
            out['error'] = mail_result.get('error') or 'Mail TLS doğrulaması başarısız.'
        return out
    except Exception as exc:
        logger.exception('bootstrap_single_server')
        messages.append(f'HATA: {exc}')
        return {
            'success': False,
            'error': str(exc),
            'paths': paths,
            'messages': messages,
            'docker_available': True,
        }
    finally:
        try:
            client.close()
        except Exception:
            pass
