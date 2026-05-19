"""Dashboard oturum yetkilendirmesi."""
from __future__ import annotations

from django.http import HttpRequest

from jir_core.permissions import can_access_panel


def require_full_session(request: HttpRequest) -> dict | None:
    """Mail sunucusu paneli API'leri için tam yetki."""
    if not request.session.get('is_logged_in'):
        return {'status': 'error', 'message': 'Oturum gerekli. Lütfen giriş yapın.'}
    if not request.session.get('can_access_panel'):
        return {
            'status': 'error',
            'message': 'Yetkiniz yok. Bu işlem için süper yönetici yetkisi gerekir.',
            'code': 'forbidden',
        }
    return None


def session_has_panel_access(request: HttpRequest) -> bool:
    if not request.session.get('is_logged_in'):
        return False
    if 'can_access_panel' in request.session:
        return bool(request.session.get('can_access_panel'))
    return can_access_panel(request.session.get('role'))
