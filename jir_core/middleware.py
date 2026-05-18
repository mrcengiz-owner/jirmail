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

        protected_paths = ['/master-panel/', '/mail-panel/', '/webmail/', '/dashboard/', '/domains/', '/accounts/', '/containers/', '/backups/', '/logs/', '/settings/', '/api/content/']
        auth_paths = [
            '/login/', '/webmail/login/', '/webmail/assets/', '/setup/',
            '/logout/', '/webmail/logout/',
            '/static/',
            '/api/health', '/api/login', '/api/test-db', '/api/setup-complete',
            '/api/installer/',
        ]

        path = request.path

        # Webmail API: oturum çerezi ile CSRF — Ninja JSON istekleri 403/500 önleme
        if path.startswith('/api/mail/') and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            request._dont_enforce_csrf_checks = True

        if not is_logged_in:
            if not any(path.startswith(auth) for auth in auth_paths):
                for protected in protected_paths:
                    if path.startswith(protected):
                        from django.shortcuts import redirect
                        if path.startswith('/webmail/'):
                            return redirect('webmail:login')
                        return redirect('login')

        response = self.get_response(request)
        return response