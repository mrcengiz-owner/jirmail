class JirInstallMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            from saas.models import SystemConfig
            config = SystemConfig.objects.first()
            if config:
                request.jir_installed = config.is_installed
                request.jir_local_key = config.jir_local_key if config.jir_local_key else 'JirCode_Alpha_2026_Secure_Key_v1'
                request.instance_id = str(config.instance_id) if config.instance_id else None
            else:
                request.jir_installed = False
                request.jir_local_key = 'JirCode_Alpha_2026_Secure_Key_v1'
                request.instance_id = None
        except Exception:
            request.jir_installed = False
            request.jir_local_key = 'JirCode_Alpha_2026_Secure_Key_v1'
            request.instance_id = None

        is_logged_in = request.session.get('is_logged_in', False)

        protected_paths = ['/master-panel/', '/mail-panel/', '/dashboard/', '/domains/', '/accounts/', '/containers/', '/backups/', '/logs/', '/settings/', '/api/content/']
        auth_paths = ['/login/', '/setup/', '/api/health', '/api/login', '/api/test-db', '/api/setup-complete']

        path = request.path

        if not is_logged_in:
            for protected in protected_paths:
                if path.startswith(protected):
                    from django.shortcuts import redirect
                    return redirect('login')

        response = self.get_response(request)
        return response