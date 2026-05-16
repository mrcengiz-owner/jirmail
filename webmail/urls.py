"""Webmail portal URL'leri — /webmail/ prefix altında."""
from django.urls import path

from . import portal_views

app_name = 'webmail'

urlpatterns = [
    path('', portal_views.inbox, name='inbox'),
    path('login/', portal_views.login_view, name='login'),
    path('logout/', portal_views.logout_view, name='logout'),
]
