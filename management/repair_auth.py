"""Onarım API yetkilendirme — installer endpoint kısıtlaması."""
from __future__ import annotations

from django.conf import settings
from django.http import HttpRequest


def resolve_jir_local_key() -> str:
    try:
        from saas.models import SystemConfig

        config = SystemConfig.objects.first()
        if config and config.jir_local_key:
            return str(config.jir_local_key).strip()
    except Exception:
        pass
    return (getattr(settings, 'JIR_LOCAL_KEY', '') or '').strip()


def session_has_repair_access(request: HttpRequest) -> bool:
    from jir_core.dashboard_auth import session_has_panel_access

    return bool(request.session.get('is_logged_in')) and session_has_panel_access(request)


def request_has_local_key(request: HttpRequest) -> bool:
    expected = resolve_jir_local_key()
    if not expected:
        return False
    supplied = (
        (request.headers.get('X-JIR-Local-Key') or '')
        or (request.headers.get('X-Jir-Local-Key') or '')
        or (request.GET.get('key') or '')
    ).strip()
    return bool(supplied) and supplied == expected


def is_setup_phase() -> bool:
    try:
        from saas.models import SystemConfig

        config = SystemConfig.objects.first()
        return not (config and config.is_installed)
    except Exception:
        return True


def deny_repair_response(message: str = 'Yetkisiz erişim.') -> dict:
    return {'status': 'error', 'message': message, 'code': 'forbidden', 'ok': False}


def require_repair_caller(request: HttpRequest) -> dict | None:
    """Panel oturumu, kurulum aşaması veya geçerli JIR_LOCAL_KEY."""
    if session_has_repair_access(request):
        return None
    if is_setup_phase():
        return None
    if request_has_local_key(request):
        return None
    return deny_repair_response(
        'Bu işlem için süper yönetici oturumu veya geçerli X-JIR-Local-Key gerekir.'
    )
