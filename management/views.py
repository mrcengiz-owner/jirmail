from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.contrib.auth import logout as django_logout
import os

INSTALLED_FLAG = os.path.join(settings.BASE_DIR, 'config', '.installed')


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
    """Decorator that checks if user has FULL role."""
    def wrapper(request, *args, **kwargs):
        if request.session.get('role') != 'FULL':
            return redirect('mail_panel')
        return view_func(request, *args, **kwargs)
    return wrapper


def get_jir_key():
    try:
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        if config and config.jir_local_key:
            return config.jir_local_key
    except Exception:
        pass
    return getattr(settings, 'JIR_LOCAL_KEY', 'JirCode_Alpha_2026_Secure_Key_v1')


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


def dashboard(request):
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')

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
        'JIR_LOCAL_KEY': get_jir_key(),
        'instance_id': instance_info['instance_id'],
        'tier': instance_info['tier'],
        'current_page': 'dashboard',
        'active_domains': active_domains,
        'active_accounts': active_accounts,
        'inactive_accounts': inactive_accounts,
        'can_manage_docker': request.session.get('role') == 'FULL',
    })


def setup(request):
    if is_installed():
        return redirect('dashboard')
    return render(request, 'setup.html')


def login(request):
    if not is_installed():
        return redirect('setup')

    if request.session.get('is_logged_in'):
        role = request.session.get('role')
        if role == 'FULL':
            return redirect('dashboard')
        return redirect('mail_panel')

    return render(request, 'login.html')


@require_http_methods(["GET"])
def mail_panel(request):
    """User Panel - Gmail style 3-column"""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')

    email = request.session.get('email', 'user@example.com')
    return render(request, 'mail_panel.html', {
        'email': email,
    })


@require_http_methods(["POST"])
@csrf_exempt
def login_success(request):
    """
    Login sonrası role bazlı yönlendirme.
    FULL role = Master Panel (Admin)
    Diğerleri = Mail Panel (User)
    """
    import json
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON', 'redirect_url': None})

    email = data.get('email')
    password = data.get('password')

    if not email or not password:
        return JsonResponse({'status': 'error', 'message': 'Email and password required', 'redirect_url': None})

    try:
        import bcrypt
        from core.models import MailAccount

        account = MailAccount.objects.filter(email=email.lower()).first()
        if not account:
            return JsonResponse({'status': 'error', 'message': 'Invalid credentials', 'redirect_url': None})

        if not bcrypt.checkpw(password.encode('utf-8'), account.password_hash.encode('utf-8')):
            return JsonResponse({'status': 'error', 'message': 'Invalid credentials', 'redirect_url': None})

        if not account.is_active:
            return JsonResponse({'status': 'error', 'message': 'Account inactive', 'redirect_url': None})

        request.session.flush()

        request.session['email'] = account.email
        request.session['role'] = account.role
        request.session['domain'] = account.domain.name
        request.session['is_logged_in'] = True
        request.session['account_id'] = account.id
        # IMAP/SMTP istemcisi için kullanıcının düz parolası geçici cache'lenir.
        # Session cookie SECURE+HttpOnly olduğu sürece tarayıcıdan erişilemez;
        # uzun vadede credential vault'a taşımak ideal.
        request.session['mail_password'] = password
        request.session.set_expiry(86400)

        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        jir_key = config.jir_local_key if config else get_jir_key()

        if account.role == 'FULL':
            redirect_url = '/dashboard/'
        else:
            redirect_url = '/mail-panel/'

        return JsonResponse({
            'status': 'success',
            'message': 'Login successful',
            'jir_key': jir_key,
            'email': account.email,
            'role': account.role,
            'redirect_url': redirect_url
        })

    except Exception as e:
        import traceback
        return JsonResponse({'status': 'error', 'message': str(e), 'redirect_url': None})


@require_http_methods(["GET", "POST"])
def logout_view(request):
    django_logout(request)
    request.session.flush()

    response = redirect('login')
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate, no-transform'
    response['Pragma'] = 'no-cache'
    response['Expires'] = '0'
    response['X-Accel-Buffering'] = 'no'
    return response


def domains_view(request):
    """Domains Management Page"""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')
    if request.session.get('role') != 'FULL':
        return redirect('mail_panel')

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
        'JIR_LOCAL_KEY': get_jir_key(),
        'domains_bootstrap': domains_bootstrap,
        'dns_provider_choices': dns_provider_choices,
        'mail_hostname': mail_hostname,
        'current_page': 'domains',
    })


def accounts_view(request):
    """Accounts Management Page"""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')
    if request.session.get('role') != 'FULL':
        return redirect('mail_panel')

    try:
        from core.models import MailDomain
        domains = list(MailDomain.objects.filter(is_active=True).values('name'))
        domains_json = [d['name'] for d in domains]
    except Exception:
        domains_json = []

    try:
        from core.models import MailAccount
        accounts = list(MailAccount.objects.all().values('email', 'username', 'domain__name', 'is_active', 'role'))
    except Exception:
        accounts = []

    return render(request, 'pages/accounts.html', {
        'JIR_LOCAL_KEY': get_jir_key(),
        'domains_json': domains_json,
        'accounts': accounts,
        'current_page': 'accounts',
    })


def containers_view(request):
    """Containers Management Page"""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')
    if request.session.get('role') != 'FULL':
        return redirect('mail_panel')

    return render(request, 'pages/containers.html', {
        'JIR_LOCAL_KEY': get_jir_key(),
        'current_page': 'containers',
    })


def backups_view(request):
    """Backups Management Page"""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')
    if request.session.get('role') != 'FULL':
        return redirect('mail_panel')

    return render(request, 'pages/backups.html', {
        'JIR_LOCAL_KEY': get_jir_key(),
        'current_page': 'backups',
    })


def logs_view(request):
    """System Logs Page"""
    if not is_installed():
        return redirect('setup')
    if not request.session.get('is_logged_in'):
        return redirect('login')
    if request.session.get('role') != 'FULL':
        return redirect('mail_panel')

    return render(request, 'pages/logs.html', {
        'JIR_LOCAL_KEY': get_jir_key(),
        'current_page': 'logs',
    })