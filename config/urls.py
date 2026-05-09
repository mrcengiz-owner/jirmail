from django.contrib import admin
from django.urls import path
from ninja import NinjaAPI
from management.api import router as management_router
from core.api import router as core_router
from management.views import dashboard, setup, login

api = NinjaAPI(title="Jîr-Mail Command Center")

api.add_router("/management/", management_router)
api.add_router("/core/", core_router)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', api.urls),
    path('dashboard/', dashboard, name='dashboard'),
    path('setup/', setup, name='setup'),
    path('login/', login, name='login'),
    path('', setup, name='root'),
]