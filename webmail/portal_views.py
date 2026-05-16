"""Webmail portal — admin panelden izole arayüz (/webmail/)."""
from __future__ import annotations

from django.contrib.auth import logout as django_logout
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from management.views import is_installed


def _require_installed(view_func):
    def wrapper(request, *args, **kwargs):
        if not is_installed():
            return redirect('setup')
        return view_func(request, *args, **kwargs)

    return wrapper


def _require_webmail_session(view_func):
    @_require_installed
    def wrapper(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return redirect('webmail:login')
        return view_func(request, *args, **kwargs)

    return wrapper


@require_http_methods(['GET'])
@_require_webmail_session
def inbox(request):
    return render(
        request,
        'webmail/inbox.html',
        {
            'email': request.session.get('email', ''),
            'role': request.session.get('role', ''),
            'is_admin': request.session.get('role') == 'FULL',
        },
    )


@require_http_methods(['GET'])
@_require_installed
def login_view(request):
    if request.session.get('is_logged_in'):
        return redirect('webmail:inbox')
    return render(request, 'webmail/login.html', {'portal_name': 'Webmail'})


@require_http_methods(['GET', 'POST'])
@_require_installed
def logout_view(request):
    django_logout(request)
    request.session.flush()
    return redirect('webmail:login')


@require_http_methods(['GET'])
def mail_panel_redirect(request):
    """Eski URL uyumluluğu."""
    return HttpResponseRedirect('/webmail/')
