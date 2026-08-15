class JirInstallMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            from saas.models import SystemConfig
            from jir_core.dashboard_auth import get_configured_local_key

            config = SystemConfig.objects.first()
            if config:
                request.jir_installed = config.is_installed
                request.jir_local_key = get_configured_local_key()
                request.instance_id = str(config.instance_id) if config.instance_id else None
            else:
                request.jir_installed = False
                request.jir_local_key = get_configured_local_key()
                request.instance_id = None
        except Exception:
            request.jir_installed = False
            request.jir_local_key = None
            request.instance_id = None

        is_logged_in = request.session.get('is_logged_in', False)

        protected_paths = ['/master-panel/', '/mail-panel/', '/webmail/', '/dashboard/', '/domains/', '/accounts/', '/containers/', '/backups/', '/logs/', '/settings/', '/repair/', '/api/content/']
        auth_paths = [
            '/login/', '/webmail/login/', '/webmail/assets/', '/setup/',
            '/logout/', '/webmail/logout/', '/yetkisiz/',
            '/static/',
            '/api/health', '/api/login', '/api/test-db', '/api/setup-complete',
            '/api/installer/',
        ]

        path = request.path

        # Webmail API CSRF: istemci X-CSRFToken gönderir (static/js/webmail/core.js).
        # Installer: yalnızca kurulum tamamlanmadan CSRF gevşetilir.
        if (
            path.startswith('/api/installer/')
            and request.method in ('POST', 'PUT', 'PATCH', 'DELETE')
            and not getattr(request, 'jir_installed', False)
        ):
            request._dont_enforce_csrf_checks = True

        if not is_logged_in:
            if not any(path.startswith(auth) for auth in auth_paths):
                for protected in protected_paths:
                    if path.startswith(protected):
                        from django.shortcuts import redirect
                        if path.startswith('/webmail/'):
                            return redirect('webmail:login')
                        return redirect('login')
        else:
            # Giriş yapmış webmail kullanıcısı mail sunucusu paneline erişemez
            from jir_core.dashboard_auth import session_has_panel_access
            from jir_core.permissions import is_panel_path

            if is_panel_path(path) and not session_has_panel_access(request):
                from django.shortcuts import render
                return render(request, 'pages/forbidden.html', {
                    'role_display': request.session.get('role_display', ''),
                })

        response = self.get_response(request)
        return response
