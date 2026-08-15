"""Dashboard / panel API yetkilendirmesi."""
from __future__ import annotations

import os
from typing import Iterable

from django.conf import settings
from django.http import HttpRequest

from jir_core.permissions import can_access_panel


WEAK_LOCAL_KEYS = frozenset({
    '',
    'change-me',
    'CHANGE_ME',
    'GENERATE_A_LONG_RANDOM_STRING',
    'JirCode_Alpha_2026_Secure_Key_v1',
})

ALLOWED_LOG_CONTAINERS = frozenset({
    'jir_postfix',
    'jir_dovecot',
    'jir_django',
    'jir_celery',
    'jir_celery_beat',
    'jir_redis',
    'jir_postgres',
    'postfix',
    'dovecot',
    'django',
    'celery',
    'celery-beat',
    'redis',
    'postgres',
})


def get_configured_local_key() -> str | None:
    """Sistem API anahtarı — hardcoded fallback yok."""
    try:
        from saas.models import SystemConfig

        config = SystemConfig.objects.first()
        if config and config.jir_local_key:
            key = str(config.jir_local_key).strip()
            if key and key not in WEAK_LOCAL_KEYS:
                return key
    except Exception:
        pass

    env_key = (getattr(settings, 'JIR_LOCAL_KEY', None) or os.getenv('JIR_LOCAL_KEY') or '').strip()
    if env_key and env_key not in WEAK_LOCAL_KEYS:
        return env_key
    return None


def request_has_service_key(request: HttpRequest) -> bool:
    """
    Servis kimliği yalnızca header ile:
    X-JIR-Local-Key (query ?key= kabul edilmez — log/referrer sızıntısı).
    """
    expected = get_configured_local_key()
    if not expected:
        return False
    provided = (
        request.headers.get('X-JIR-Local-Key')
        or request.META.get('HTTP_X_JIR_LOCAL_KEY')
        or ''
    ).strip()
    return bool(provided) and provided == expected


def _refresh_panel_flag_from_db(request: HttpRequest) -> bool | None:
    """account_id varsa rolü DB'den doğrula; yoksa None."""
    account_id = request.session.get('account_id')
    if not account_id:
        return None
    try:
        from core.models import MailAccount

        account = MailAccount.objects.filter(pk=account_id, is_active=True).only('role').first()
        if not account:
            return False
        panel = can_access_panel(account.role)
        request.session['role'] = account.role
        request.session['can_access_panel'] = panel
        return panel
    except Exception:
        return None


def session_has_panel_access(request: HttpRequest) -> bool:
    if not request.session.get('is_logged_in'):
        return False
    refreshed = _refresh_panel_flag_from_db(request)
    if refreshed is not None:
        return refreshed
    if 'can_access_panel' in request.session:
        return bool(request.session.get('can_access_panel'))
    return can_access_panel(request.session.get('role'))


def require_full_session(request: HttpRequest) -> dict | None:
    """Mail sunucusu paneli API'leri için tam yetki (oturum)."""
    if not request.session.get('is_logged_in'):
        return {'status': 'error', 'message': 'Oturum gerekli. Lütfen giriş yapın.', 'code': 'auth_required'}
    if not session_has_panel_access(request):
        return {
            'status': 'error',
            'message': 'Yetkiniz yok. Bu işlem için süper yönetici yetkisi gerekir.',
            'code': 'forbidden',
        }
    return None


def require_panel_api(request: HttpRequest) -> dict | None:
    """Panel oturumu veya X-JIR-Local-Key servis anahtarı."""
    if session_has_panel_access(request):
        return None
    if request_has_service_key(request):
        return None
    if request.session.get('is_logged_in'):
        return {
            'status': 'error',
            'message': 'Yetkiniz yok. Bu işlem için süper yönetici yetkisi gerekir.',
            'code': 'forbidden',
        }
    return {'status': 'error', 'message': 'Oturum gerekli. Lütfen giriş yapın.', 'code': 'auth_required'}


def is_self_account(request: HttpRequest, email: str) -> bool:
    session_email = (request.session.get('email') or '').strip().lower()
    return bool(session_email) and session_email == (email or '').strip().lower()


def require_self_or_panel(request: HttpRequest, email: str) -> dict | None:
    """Kendi hesabı veya panel yetkisi."""
    if session_has_panel_access(request) or request_has_service_key(request):
        return None
    if request.session.get('is_logged_in') and is_self_account(request, email):
        return None
    return {'status': 'error', 'message': 'Yetkisiz erişim!', 'code': 'forbidden'}


def system_is_installed() -> bool:
    try:
        from saas.models import SystemConfig

        config = SystemConfig.objects.first()
        if config:
            return bool(config.is_installed)
    except Exception:
        pass
    flag = os.path.join(settings.BASE_DIR, 'config', '.installed')
    return os.path.exists(flag)


def require_installer_access(
    request: HttpRequest,
    *,
    allow_panel_when_installed: bool = False,
) -> dict | None:
    """
    Kurulum öncesi: açık.
    Kurulum sonrası: varsayılan kapalı; allow_panel_when_installed ise FULL panel.
    """
    if not system_is_installed():
        return None
    if allow_panel_when_installed:
        return require_panel_api(request)
    return {
        'status': 'error',
        'message': 'Sistem zaten kurulu. Kurulum API’leri kapatıldı.',
        'code': 'already_installed',
    }


def is_allowed_log_container(name: str) -> bool:
    return (name or '').strip() in ALLOWED_LOG_CONTAINERS


def safe_extract_tar(tar, destination: str, *, members: Iterable | None = None) -> None:
    """Zip Slip / path traversal korumalı extractall."""
    dest = os.path.realpath(destination)
    os.makedirs(dest, exist_ok=True)
    selected = members if members is not None else tar.getmembers()
    for member in selected:
        member_path = os.path.realpath(os.path.join(dest, member.name))
        if member_path != dest and not member_path.startswith(dest + os.sep):
            raise ValueError(f'Güvensiz arşiv yolu: {member.name}')
    # Python 3.12+: filter='data' ek koruma
    try:
        tar.extractall(dest, members=selected, filter='data')
    except TypeError:
        tar.extractall(dest, members=selected)
