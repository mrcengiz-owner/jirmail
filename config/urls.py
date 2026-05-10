from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
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

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('dashboard/', dashboard, name='dashboard'),
    path('setup/', setup, name='setup'),
    path('login/', login, name='login'),
    path('login-success/', login_success, name='login_success'),
    path('logout/', logout_view, name='logout'),
    path('master-panel/', master_panel, name='master_panel'),
    path('mail-panel/', mail_panel, name='mail_panel'),
    path('', root_redirect, name='root'),
]