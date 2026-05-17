"""Webmail portal — admin panelden izole arayüz (/webmail/)."""
from __future__ import annotations

from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from jir_core.session_auth import logout_response
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
@ensure_csrf_cookie
@_require_webmail_session
def inbox(request):
    from django.template.response import TemplateResponse
    from core.models import MailAccount

    account = MailAccount.objects.filter(
        pk=request.session.get('account_id'),
    ).select_related('domain').first()

    ai_on = False
    if account and account.is_active:
        try:
            ai_on = bool(account.ai_available)
        except Exception:
            ai_on = False

    ctx = {
        'email': request.session.get('email', ''),
        'role': request.session.get('role', ''),
        'is_admin': request.session.get('role') == 'FULL',
        'ai_enabled': ai_on,
    }
    return TemplateResponse(
        request,
        ['webmail/pages/inbox.html', 'webmail/inbox.html'],
        ctx,
    )


@require_http_methods(['GET'])
@ensure_csrf_cookie
@_require_installed
def login_view(request):
    if request.session.get('is_logged_in'):
        return redirect('webmail:inbox')
    return render(request, 'webmail/login.html', {'portal_name': 'Webmail'})


@require_http_methods(['GET', 'POST'])
@csrf_exempt
@_require_installed
def logout_view(request):
    return logout_response(request)


@require_http_methods(['GET'])
def mail_panel_redirect(request):
    """Eski URL uyumluluğu."""
    return HttpResponseRedirect('/webmail/')
