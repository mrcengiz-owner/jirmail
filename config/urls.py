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
from management.views import (
    dashboard, setup, login, master_panel, mail_panel, login_success, logout_view,
    domains_view, accounts_view, containers_view, backups_view, logs_view
)
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
    from management.views import get_jir_key, get_instance_info
    from core.models import MailAccount, MailDomain
    template_map = {
        'domains': 'partials/domains.html',
        'accounts': 'partials/accounts.html',
        'backup': 'partials/backup.html',
        'logs': 'partials/logs.html',
        'containers': 'partials/containers.html',
        'dashboard': 'partials/dashboard.html',
        'navbar-stats': 'partials/navbar_stats.html',
    }
    template_name = template_map.get(tab, 'partials/dashboard.html')
    try:
        template = loader.get_template(template_name)
        jir_key = get_jir_key()
        context = {'JIR_LOCAL_KEY': jir_key}

        if tab == 'dashboard':
            instance_info = get_instance_info()
            context.update({
                'instance_id': instance_info['instance_id'],
                'tier': instance_info['tier'],
            })

        if tab == 'accounts':
            try:
                domains = list(MailDomain.objects.filter(is_active=True).values('name'))
                context['domains_json'] = [d['name'] for d in domains]
            except Exception:
                context['domains_json'] = []

        if tab == 'navbar-stats':
            context['active_domains'] = MailDomain.objects.filter(is_active=True).count()
            context['active_accounts'] = MailAccount.objects.filter(is_active=True).count()
            context['inactive_accounts'] = MailAccount.objects.filter(is_active=False).count()

        return HttpResponse(template.render(context, request))
    except Exception as e:
        return HttpResponse(f'<div class="p-6 text-red-400">Error loading {tab}: {str(e)}</div>', status=500)

def favicon(request):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#10b981"/><path d="M8 16l5 5 11-11" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
    return HttpResponse(svg, content_type='image/svg+xml')

def well_known(request, path=''):
    return HttpResponse(status=204)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls, name='api'),
    path('api/content/<str:tab>/', content_partial, name='api_content'),

    # Main pages (traditional multi-page, not HTMX SPA)
    path('dashboard/', dashboard, name='dashboard'),
    path('domains/', domains_view, name='domains'),
    path('accounts/', accounts_view, name='accounts'),
    path('containers/', containers_view, name='containers'),
    path('backups/', backups_view, name='backups'),
    path('logs/', logs_view, name='logs'),

    path('setup/', setup, name='setup'),
    path('login/', login, name='login'),
    path('login-success/', login_success, name='login_success'),
    path('logout/', logout_view, name='logout'),
    path('master-panel/', master_panel, name='master_panel'),
    path('mail-panel/', mail_panel, name='mail_panel'),
    path('favicon.ico', favicon),
    path('.well-known/<path:path>', well_known),
    path('', root_redirect, name='root'),
]

# Serve static files in development mode
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])