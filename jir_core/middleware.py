class JirInstallMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            from saas.models import SystemConfig
            config = SystemConfig.objects.first()
            if config:
                request.jir_installed = config.is_installed
                if config.jir_local_key:
                    request.jir_local_key = config.jir_local_key
                if config.instance_id:
                    request.instance_id = config.instance_id
            else:
                request.jir_installed = False
                request.jir_local_key = 'JirCode_Alpha_2026_Secure_Key_v1'
                request.instance_id = None
        except Exception:
            request.jir_installed = False
            request.jir_local_key = 'JirCode_Alpha_2026_Secure_Key_v1'
            request.instance_id = None

        response = self.get_response(request)
        return response