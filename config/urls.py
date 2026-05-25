from django.contrib import admin
from django.urls import path, include
from django.shortcuts import redirect
from django.http import HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from ninja import NinjaAPI
from management.api import router as management_router
from core.api import router as core_router
from backup.api import router as backup_router
from alerts.api import router as alerts_router
from installer.api import router as installer_router
from installer.api import install_stream
from webmail.api import router as webmail_router
from webmail.api import mail_stream
from webmail.portal_views import mail_panel_redirect
from monitoring.api import router as monitoring_router
from monitoring.api import logs_stream
from management.views import (
    dashboard, setup, login, login_success, logout_view, forbidden_view,
    domains_view, accounts_view, containers_view, backups_view, logs_view, settings_view, repair_view,
)
from management.views import is_installed as check_installed

api = NinjaAPI(title="Jîr-Mail Command Center")

api.add_router("/management/", management_router)
api.add_router("/core/", core_router)
api.add_router("/backup/", backup_router)
api.add_router("/alerts/", alerts_router)
api.add_router("/installer/", installer_router)
api.add_router("/mail/", webmail_router)
api.add_router("/monitoring/", monitoring_router)


def root_redirect(request):
    if not check_installed():
        return redirect('setup')
    if request.session.get('is_logged_in'):
        from jir_core.dashboard_auth import session_has_panel_access
        if session_has_panel_access(request):
            return redirect('dashboard')
        return redirect('webmail:inbox')
    return redirect('login')


def favicon(request):
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#10b981"/><path d="M8 16l5 5 11-11" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" fill="none"/></svg>'
    return HttpResponse(svg, content_type='image/svg+xml')


def well_known(request, path=''):
    return HttpResponse(status=204)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls, name='api'),
    path('api/installer/stream/<str:run_id>', install_stream, name='installer_stream'),
    path('api/mail/stream', mail_stream, name='mail_stream'),
    path('api/monitoring/logs/stream', logs_stream, name='monitoring_logs_stream'),

    path('dashboard/', dashboard, name='dashboard'),
    path('domains/', domains_view, name='domains'),
    path('accounts/', accounts_view, name='accounts'),
    path('containers/', containers_view, name='containers'),
    path('backups/', backups_view, name='backups'),
    path('logs/', logs_view, name='logs'),
    path('settings/', settings_view, name='settings'),
    path('repair/', repair_view, name='repair'),

    path('setup/', setup, name='setup'),
    path('login/', login, name='login'),
    path('login-success/', login_success, name='login_success'),
    path('logout/', logout_view, name='logout'),
    path('yetkisiz/', forbidden_view, name='forbidden'),
    path('webmail/', include('webmail.urls')),
    path('mail-panel/', mail_panel_redirect, name='mail_panel'),
    path('favicon.ico', favicon),
    path('.well-known/<path:path>', well_known),
    path('', root_redirect, name='root'),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATICFILES_DIRS[0])
