"""Dashboard oturum yetkilendirmesi."""
from __future__ import annotations

from django.http import HttpRequest


def require_full_session(request: HttpRequest) -> dict | None:
    if not request.session.get('is_logged_in'):
        return {'status': 'error', 'message': 'Oturum gerekli. Lütfen giriş yapın.'}
    if request.session.get('role') != 'FULL':
        return {'status': 'error', 'message': 'Bu işlem için tam yetki gerekir.'}
    return None
