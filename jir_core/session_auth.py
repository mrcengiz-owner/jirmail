"""Oturum açma / çıkış — dashboard ve webmail ortak."""
from __future__ import annotations

from django.contrib.auth import logout as django_logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect


def clear_mail_session(request: HttpRequest) -> None:
    django_logout(request)
    request.session.flush()


def logout_response(request: HttpRequest) -> HttpResponse:
    """Çıkış sonrası doğru login sayfasına yönlendir."""
    clear_mail_session(request)
    path = (request.path or '').lower()
    if path.startswith('/webmail'):
        target = 'webmail:login'
    else:
        target = 'login'
    response = redirect(target)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    return response
