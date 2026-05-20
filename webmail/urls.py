"""Webmail portal URL'leri — /webmail/ prefix altında."""
from django.urls import path

from . import asset_views, portal_views

app_name = 'webmail'

urlpatterns = [
    path('assets/<path:asset_path>', asset_views.serve_asset, name='asset'),
    path('', portal_views.inbox, name='inbox'),
    path('settings/', portal_views.settings_view, name='settings'),
    path('login/', portal_views.login_view, name='login'),
    path('logout/', portal_views.logout_view, name='logout'),
]
