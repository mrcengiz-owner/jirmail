from django.shortcuts import render, redirect
from django.conf import settings

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

def dashboard(request):
    if not is_installed():
        return redirect('setup')

    return render(request, 'dashboard.html', {
        'JIR_LOCAL_KEY': get_jir_key()
    })

def setup(request):
    if is_installed():
        return redirect('dashboard')
    return render(request, 'setup.html')

def login(request):
    if not is_installed():
        return redirect('setup')
    return render(request, 'login.html')
