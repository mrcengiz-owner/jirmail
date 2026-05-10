from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse

def is_installed():
    try:
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        return config and config.is_installed
    except Exception:
        return False

def get_jir_key():
    try:
        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        if config and config.jir_local_key:
            return config.jir_local_key
    except Exception:
        pass
    return 'JirCode_Alpha_2026_Secure_Key_v1'

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

    instance_info = get_instance_info()
    return render(request, 'master_panel.html', {
        'JIR_LOCAL_KEY': get_jir_key(),
        'instance_id': instance_info['instance_id'],
        'tier': instance_info['tier'],
    })

def setup(request):
    if is_installed():
        return redirect('dashboard')
    return render(request, 'setup.html')

def login(request):
    if not is_installed():
        return redirect('setup')
    return render(request, 'login.html')

def master_panel(request):
    """Admin Panel - System Specs, Domain Control, User Logs, Backup"""
    if not is_installed():
        return redirect('setup')

    if request.session.get('role') != 'FULL':
        return redirect('mail_panel')

    instance_info = get_instance_info()
    return render(request, 'master_panel.html', {
        'JIR_LOCAL_KEY': get_jir_key(),
        'instance_id': instance_info['instance_id'],
        'tier': instance_info['tier'],
    })

def mail_panel(request):
    """User Panel - Gmail style 3-column"""
    if not is_installed():
        return redirect('setup')

    email = request.session.get('email', 'user@example.com')
    return render(request, 'mail_panel.html', {
        'email': email,
    })

def login_success(request):
    """
    Login sonrası role bazlı yönlendirme.
    FULL role = Master Panel (Admin)
    Diğerleri = Mail Panel (User)
    """
    import json
    data = json.loads(request.body)
    email = data.get('email')
    password = data.get('password')

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

        request.session['email'] = account.email
        request.session['role'] = account.role
        request.session['domain'] = account.domain.name
        request.session.set_expiry(86400)

        from saas.models import SystemConfig
        config = SystemConfig.objects.first()
        jir_key = config.jir_local_key if config else get_jir_key()

        if account.role == 'FULL':
            redirect_url = '/master-panel/'
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
        return JsonResponse({'status': 'error', 'message': str(e), 'redirect_url': None})


def logout_view(request):
    request.session.flush()
    return redirect('login')