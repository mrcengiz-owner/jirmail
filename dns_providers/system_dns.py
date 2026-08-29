"""Kurulumda kaydedilen global DNS sağlayıcı ayarları ve domain otomasyonu."""
from __future__ import annotations

import logging
import os
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def resolve_mail_hostname(domain_name: str = '') -> str:
    """SMTP/IMAP hostname — env MAIL_HOSTNAME veya mail.{domain}."""
    explicit = (
        os.getenv('MAIL_HOSTNAME', '').strip()
        or getattr(settings, 'MAIL_SERVER_HOSTNAME', None)
        or ''
    )
    if explicit:
        return str(explicit).strip().lower()
    domain_name = (domain_name or os.getenv('MAIL_DOMAIN', '') or '').strip().lower()
    if domain_name:
        return f'mail.{domain_name}'
    return 'mail.local'


def credentials_configured(provider_name: str, credentials: dict | None) -> bool:
    """Provider için minimum credential alanları dolu mu?"""
    from . import get_provider

    try:
        provider = get_provider(provider_name, credentials or {})
        return provider.is_configured()
    except Exception:
        return False


def persist_system_dns_config(provider_name: str, credentials: dict | None) -> None:
    """Kurulum / DNS adımında global sağlayıcı bilgisini SystemConfig'e yazar."""
    from saas.models import SystemConfig

    provider_name = (provider_name or 'manual').lower()
    credentials = dict(credentials or {})
    cfg = SystemConfig.objects.first()
    if not cfg:
        return
    cfg.dns_provider = provider_name
    cfg.dns_credentials = credentials
    cfg.save(update_fields=['dns_provider', 'dns_credentials', 'updated_at'])


def _fallback_from_installation_run() -> tuple[str, dict] | None:
    try:
        from installer.models import InstallationRun

        run = (
            InstallationRun.objects.filter(status='completed')
            .order_by('-finished_at')
            .first()
        )
        if not run or not run.config_snapshot:
            return None
        snap = run.config_snapshot
        provider = (snap.get('dns_provider') or 'manual').lower()
        credentials = snap.get('dns_credentials') or {}
        if provider == 'manual' or not credentials_configured(provider, credentials):
            return None
        return provider, credentials
    except Exception as exc:
        logger.debug('installation run DNS fallback: %s', exc)
        return None


def _fallback_from_domain() -> tuple[str, dict] | None:
    try:
        from core.models import MailDomain

        domain = (
            MailDomain.objects.exclude(dns_provider='manual')
            .exclude(dns_credentials={})
            .order_by('created_at')
            .first()
        )
        if not domain:
            return None
        provider = (domain.dns_provider or 'manual').lower()
        credentials = domain.dns_credentials or {}
        if provider == 'manual' or not credentials_configured(provider, credentials):
            return None
        return provider, credentials
    except Exception as exc:
        logger.debug('domain DNS fallback: %s', exc)
        return None


def get_system_dns_config(*, persist_fallback: bool = True) -> tuple[str, dict]:
    """
    Kurulumda girilen DNS sağlayıcı bilgisini döndürür.

    Öncelik: SystemConfig → son başarılı kurulum → herhangi bir domain kaydı.
    """
    from saas.models import SystemConfig

    cfg = SystemConfig.objects.first()
    if cfg:
        provider = (cfg.dns_provider or 'manual').lower()
        credentials = dict(cfg.dns_credentials or {})
        if provider != 'manual' and credentials_configured(provider, credentials):
            return provider, credentials

    for fallback in (_fallback_from_installation_run, _fallback_from_domain):
        found = fallback()
        if found:
            provider, credentials = found
            if persist_fallback:
                persist_system_dns_config(provider, credentials)
            return provider, credentials

    return 'manual', {}


def auto_apply_domain_dns(
    domain_obj,
    *,
    server_ip: str = '',
    mail_hostname: str = '',
    provider_name: str | None = None,
    credentials: dict | None = None,
) -> dict[str, Any]:
    """
    Yeni domain için DKIM üretir ve kayıtlı sağlayıcı varsa zone'a yazar.

    Manuel sağlayıcıda veya credential yoksa yalnızca DKIM/SPF/DMARC model alanları doldurulur.
    """
    from dns_providers.records import apply_mail_dns, detect_public_ip

    if not domain_obj.dkim_private_key or not domain_obj.dkim_record:
        domain_obj.generate_dkim_keys()

    provider = (provider_name or domain_obj.dns_provider or '').lower()
    creds = credentials
    if creds is None and (not provider or provider == 'manual'):
        provider, creds = get_system_dns_config()

    if not provider or provider == 'manual':
        return {
            'applied': False,
            'skipped': True,
            'message': 'Manuel DNS — kayıtlar panoda gösterilecek',
        }

    if creds is None:
        creds = domain_obj.dns_credentials or {}

    if not credentials_configured(provider, creds):
        return {
            'applied': False,
            'skipped': True,
            'message': f'{provider} credential bulunamadı — kurulumda API anahtarı girildi mi?',
        }

    mail_host = (mail_hostname or resolve_mail_hostname(domain_obj.name)).strip().lower()
    ip = (server_ip or detect_public_ip() or '').strip()

    try:
        outcome = apply_mail_dns(
            domain_obj.name,
            provider_name=provider,
            credentials=creds,
            server_ip=ip,
            mail_hostname=mail_host,
            domain_obj=domain_obj,
        )
    except Exception as exc:
        logger.exception('auto_apply_domain_dns failed for %s', domain_obj.name)
        return {
            'applied': False,
            'skipped': False,
            'success': False,
            'message': str(exc),
        }

    outcome['applied'] = not outcome.get('skipped')
    if outcome.get('success'):
        outcome['message'] = (
            f'DNS kayıtları Cloudflare zone\'a yazıldı ({outcome.get("created", 0)}/{outcome.get("total", 0)})'
            if provider == 'cloudflare'
            else f'DNS kayıtları uygulandı ({outcome.get("created", 0)}/{outcome.get("total", 0)})'
        )
    elif outcome.get('partial'):
        outcome['message'] = (
            f'DNS kısmen uygulandı ({outcome.get("created", 0)}/{outcome.get("total", 0)})'
        )
    elif not outcome.get('skipped'):
        outcome['message'] = outcome.get('message') or 'DNS uygulanamadı'

    return outcome
