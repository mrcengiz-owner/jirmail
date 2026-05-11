from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from ninja import NinjaAPI
from management.api import router as management_router
from core.api import router as core_router
from backup.api import router as backup_router
from alerts.api import router as alerts_router
from management.views import dashboard, setup, login, master_panel, mail_panel, login_success, logout_view
from management.views import is_installed as check_installed

api = NinjaAPI(title="Jîr-Mail Command Center")

api.add_router("/management/", management_router)
api.add_router("/core/", core_router)
api.add_router("/backup/", backup_router)
api.add_router("/alerts/", alerts_router)

def root_redirect(request):
    if check_installed():
        return redirect('dashboard')
    return redirect('setup')

def content_partial(request, tab):
    from django.template import loader
    template_map = {
        'domains': 'partials/domains.html',
        'accounts': 'partials/accounts.html',
        'backup': 'partials/backup.html',
        'logs': 'partials/logs.html',
        'containers': 'partials/containers.html',
        'dashboard': 'partials/dashboard.html',
    }
    template_name = template_map.get(tab, 'partials/dashboard.html')
    try:
        template = loader.get_template(template_name)
        context = {}
        if tab == 'dashboard':
            from management.views import get_jir_key, get_instance_info
            instance_info = get_instance_info()
            context = {
                'JIR_LOCAL_KEY': get_jir_key(),
                'instance_id': instance_info['instance_id'],
                'tier': instance_info['tier'],
            }
        return HttpResponse(template.render(context, request))
    except Exception as e:
        return HttpResponse(f'<div class="p-6 text-red-400">Error loading {tab}: {str(e)}</div>', status=500)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls, name='api'),
    path('api/content/<str:tab>/', content_partial, name='api_content'),
    path('dashboard/', dashboard, name='dashboard'),
    path('setup/', setup, name='setup'),
    path('login/', login, name='login'),
    path('login-success/', login_success, name='login_success'),
    path('logout/', logout_view, name='logout'),
    path('master-panel/', master_panel, name='master_panel'),
    path('mail-panel/', mail_panel, name='mail_panel'),
    path('', root_redirect, name='root'),
] + static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])