from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse
from jir_core.dashboard_auth import session_has_panel_access
from jir_core.permissions import apply_account_session
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import ensure_csrf_cookie
from jir_core.session_auth import logout_response
import os

INSTALLED_FLAG = os.path.join(settings.BASE_DIR, 'config', '.installed')


def _docker_api_available_for_panel() -> bool:
    try:
        from management.compose_status import docker_api_available

        return docker_api_available()
    except Exception:
        return False


def is_installed():
    """
    Check installation status:
    Primary source: SystemConfig database (highest truth)
    Secondary: .installed flag file
    """
    try:
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        if config:
            return config.is_installed
    except Exception:
        pass

    if os.path.exists(INSTALLED_FLAG):
        return True

    return False


def require_installation(view_func):
    """Decorator that redirects to setup if system is not installed."""
    def wrapper(request, *args, **kwargs):
        if not is_installed():
            return redirect('setup')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_session(view_func):
    """Decorator that checks if user has valid session."""
    def wrapper(request, *args, **kwargs):
        if not request.session.get('is_logged_in'):
            return redirect('login')
        return view_func(request, *args, **kwargs)
    return wrapper


def require_full_access(view_func):
    """Mail sunucusu paneli — süper yönetici (FULL) gerekir."""
    def wrapper(request, *args, **kwargs):
        denied = require_panel_page(request)
        if denied:
            return denied
        return view_func(request, *args, **kwargs)
    return wrapper


def require_panel_page(request):
    """Panel sayfaları için oturum + süper yönetici kontrolü."""
    if not request.session.get('is_logged_in'):
        return redirect('login')
    if not session_has_panel_access(request):
        return render(request, 'pages/forbidden.html', {
            'role_display': request.session.get('role_display', ''),
        })
    return None


def forbidden_view(request):
    """Yetkisiz panel erişimi."""
    if not request.session.get('is_logged_in'):
        return redirect('login')
    return render(request, 'pages/forbidden.html', {
        'role_display': request.session.get('role_display', ''),
    })


def get_jir_key():
    """Yalnızca sunucu tarafı kullanım — template'e basılmamalı."""
    from jir_core.dashboard_auth import get_configured_local_key
    return get_configured_local_key() or ''


def get_instance_info():
    try:
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        if config:
            return {
                'instance_id': str(config.instance_id),
                'tier': config.tier,
            }
    except Exception:
        pass
    return {'instance_id': 'N/A', 'tier': 'FREE'}


@ensure_csrf_cookie
def dashboard(request):
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    instance_info = get_instance_info()

    try:
        from core.models import MailAccount, MailDomain
        active_domains = MailDomain.objects.filter(is_active=True).count()
        active_accounts = MailAccount.objects.filter(is_active=True).count()
        inactive_accounts = MailAccount.objects.filter(is_active=False).count()
    except Exception:
        active_domains = 0
        active_accounts = 0
        inactive_accounts = 0

    return render(request, 'pages/dashboard.html', {
        'instance_id': instance_info['instance_id'],
        'tier': instance_info['tier'],
        'current_page': 'dashboard',
        'active_domains': active_domains,
        'active_accounts': active_accounts,
        'inactive_accounts': inactive_accounts,
        'can_manage_docker': (
            session_has_panel_access(request)
            and _docker_api_available_for_panel()
        ),
    })


@ensure_csrf_cookie
def setup(request):
    if is_installed():
        return redirect('dashboard')
    return render(request, 'setup.html')


@ensure_csrf_cookie
def login(request):
    if not is_installed():
        return redirect('setup')

    if request.session.get('is_logged_in'):
        if session_has_panel_access(request):
            return redirect('dashboard')
        return redirect('webmail:inbox')

    return render(request, 'login.html')


@require_http_methods(["GET"])
def mail_panel(request):
    """Eski URL — izole webmail portalına yönlendir."""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')
    return redirect('webmail:inbox')


@require_http_methods(["POST"])
def login_success(request):
    """
    Login sonrası role bazlı yönlendirme.
    FULL role = Master Panel (Admin)
    Diğerleri = Mail Panel (User)
    """
    import json
    from jir_core.login_throttle import (
        clear_login_failures,
        login_blocked,
        record_login_failure,
    )
    from jir_core.session_secrets import store_mail_password

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON', 'redirect_url': None})

    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return JsonResponse({'status': 'error', 'message': 'Email and password required', 'redirect_url': None})

    blocked = login_blocked(request, email)
    if blocked:
        return JsonResponse({'status': 'error', 'message': blocked, 'redirect_url': None})

    try:
        import bcrypt
        from core.models import MailAccount

        account = MailAccount.objects.filter(email=email.lower()).first()
        if not account:
            record_login_failure(request, email)
            return JsonResponse({'status': 'error', 'message': 'Invalid credentials', 'redirect_url': None})

        if not bcrypt.checkpw(password.encode('utf-8'), account.password_hash.encode('utf-8')):
            record_login_failure(request, email)
            return JsonResponse({'status': 'error', 'message': 'Invalid credentials', 'redirect_url': None})

        if not account.is_active:
            return JsonResponse({'status': 'error', 'message': 'Account inactive', 'redirect_url': None})

        request.session.flush()

        permissions = apply_account_session(request, account)
        store_mail_password(request.session, password)
        request.session.set_expiry(getattr(settings, 'SESSION_COOKIE_AGE', 28800))
        request.session.modified = True
        request.session.save()
        clear_login_failures(request, email)

        if account.can_access_panel:
            redirect_url = '/dashboard/'
        else:
            redirect_url = '/webmail/'

        return JsonResponse({
            'status': 'success',
            'message': 'Login successful',
            'email': account.email,
            'role': account.role,
            'role_display': account.get_role_display(),
            'permissions': permissions,
            'can_access_panel': permissions.get('can_access_panel', False),
            'is_superuser': account.is_bootstrap_admin(),
            'redirect_url': redirect_url,
        })

    except Exception:
        import logging
        logging.getLogger(__name__).exception('Login failed')
        return JsonResponse({'status': 'error', 'message': 'Giriş başarısız', 'redirect_url': None})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    return logout_response(request)


def domains_view(request):
    """Domains Management Page"""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    try:
        from core.models import MailDomain
        domains_qs = MailDomain.objects.all().order_by('name')
        domains_bootstrap = [
            {
                'id': d.id,
                'name': d.name,
                'is_active': d.is_active,
                'dkim_enabled': d.dkim_enabled,
                'verification_status': d.verification_status,
                'spf_record': d.spf_record or '',
                'dkim_record': d.dkim_record or '',
                'dmarc_record': d.dmarc_record or '',
                'dns_provider': d.dns_provider,
            }
            for d in domains_qs
        ]
        dns_provider_choices = [
            {'value': c[0], 'label': c[1]} for c in MailDomain.DNS_PROVIDER_CHOICES
        ]
    except Exception:
        domains_bootstrap = []
        dns_provider_choices = []

    mail_hostname = (getattr(settings, 'MAIL_SERVER_HOSTNAME', None) or '').strip()

    return render(request, 'pages/domains.html', {
        'domains_bootstrap': domains_bootstrap,
        'dns_provider_choices': dns_provider_choices,
        'mail_hostname': mail_hostname,
        'current_page': 'domains',
    })


def accounts_view(request):
    """Accounts Management Page"""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    try:
        from core.models import MailDomain
        domains = list(MailDomain.objects.filter(is_active=True).values('name'))
        domains_json = [d['name'] for d in domains]
    except Exception:
        domains_json = []

    try:
        from core.models import MailAccount
        accounts = []
        for acc in MailAccount.objects.select_related('domain').all():
            perms = acc.permissions_summary()
            accounts.append({
                'email': acc.email,
                'username': acc.username,
                'domain__name': acc.domain.name,
                'is_active': acc.is_active,
                'role': acc.role,
                'role_display': acc.get_role_display(),
                'is_superuser': acc.is_bootstrap_admin(),
                'permissions': perms,
            })
    except Exception:
        accounts = []

    from jir_core.permissions import ROLE_CHOICES_FOR_UI

    return render(request, 'pages/accounts.html', {
        'domains_json': domains_json,
        'accounts_bootstrap': accounts,
        'role_choices_json': ROLE_CHOICES_FOR_UI,
        'current_page': 'accounts',
    })


def containers_view(request):
    """Containers Management Page"""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    try:
        from installer.compose_mode import is_compose_stack

        compose_mode = is_compose_stack()
    except Exception:
        compose_mode = False

    return render(request, 'pages/containers.html', {
        'current_page': 'containers',
        'compose_stack': compose_mode,
    })


def backups_view(request):
    """Backups Management Page"""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    return render(request, 'pages/backups.html', {
        'current_page': 'backups',
    })


def logs_view(request):
    """System Logs Page"""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    return render(request, 'pages/logs.html', {
        'current_page': 'logs',
    })


def settings_view(request):
    """Kurulum sonrası sistem ayarları (Docker adları, yollar; veritabanı salt okunur)."""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    return render(request, 'pages/settings.html', {
        'current_page': 'settings',
    })


@ensure_csrf_cookie
def repair_view(request):
    """Mail stack onarım — yalnızca süper yönetici."""
    if not is_installed():
        return redirect('setup')
    denied = require_panel_page(request)
    if denied:
        return denied

    return render(request, 'pages/repair.html', {
        'current_page': 'repair',
    })