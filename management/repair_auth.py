"""Onarım API yetkilendirme — installer endpoint kısıtlaması."""
from __future__ import annotations

from django.http import HttpRequest

from jir_core.dashboard_auth import (
    get_configured_local_key,
    request_has_service_key,
    session_has_panel_access,
    system_is_installed,
)


def resolve_jir_local_key() -> str:
    return get_configured_local_key() or ''


def session_has_repair_access(request: HttpRequest) -> bool:
    return bool(request.session.get('is_logged_in')) and session_has_panel_access(request)


def request_has_local_key(request: HttpRequest) -> bool:
    """Yalnızca X-JIR-Local-Key header (query ?key= kabul edilmez)."""
    return request_has_service_key(request)


def is_setup_phase() -> bool:
    return not system_is_installed()


def deny_repair_response(message: str = 'Yetkisiz erişim.') -> dict:
    return {'status': 'error', 'message': message, 'code': 'forbidden', 'ok': False}


def require_repair_caller(request: HttpRequest) -> dict | None:
    """Panel oturumu, kurulum aşaması veya geçerli X-JIR-Local-Key."""
    if session_has_repair_access(request):
        return None
    if is_setup_phase():
        return None
    if request_has_local_key(request):
        return None
    return deny_repair_response(
        'Bu işlem için süper yönetici oturumu veya geçerli X-JIR-Local-Key gerekir.'
    )
