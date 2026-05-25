"""Mail hesabı rolleri ve panel/webmail yetkileri."""
from __future__ import annotations

from typing import Any

from core.models import MailRole

# Mail sunucusu yönetim paneli (dashboard ve alt sayfalar)
PANEL_PATH_PREFIXES: tuple[str, ...] = (
    '/dashboard/',
    '/domains/',
    '/accounts/',
    '/containers/',
    '/backups/',
    '/logs/',
    '/settings/',
    '/repair/',
    '/master-panel/',
    '/mail-panel/',
)


def can_access_panel(role: str | None) -> bool:
    """Mail sunucusu / yönetim paneline erişim."""
    return (role or '') == MailRole.FULL_ACCESS


def role_permissions(role: str | None) -> dict[str, Any]:
    """Rol için görünür yetki özeti (oturum ve API yanıtları)."""
    role = role or MailRole.WEBMAIL_USER
    panel = can_access_panel(role)
    return {
        'role': role,
        'can_access_panel': panel,
        'can_send_mail': role in (
            MailRole.FULL_ACCESS,
            MailRole.WEBMAIL_USER,
            MailRole.SEND_ONLY,
        ),
        'can_receive_mail': role in (
            MailRole.FULL_ACCESS,
            MailRole.WEBMAIL_USER,
            MailRole.RECEIVE_ONLY,
        ),
        'can_manage_accounts': panel,
        'can_manage_domains': panel,
        'can_manage_containers': panel,
        'label': dict(MailRole.choices).get(role, role),
    }


def apply_account_session(request, account) -> dict[str, Any]:
    """Giriş sonrası oturuma rol ve yetkileri yazar."""
    perms = role_permissions(account.role)
    request.session['email'] = account.email
    request.session['role'] = account.role
    request.session['domain'] = account.domain.name
    request.session['is_logged_in'] = True
    request.session['account_id'] = account.id
    request.session['can_access_panel'] = perms['can_access_panel']
    request.session['role_display'] = account.get_role_display()
    request.session['permissions'] = perms
    request.session['is_superuser'] = account.is_bootstrap_admin()
    return perms


def is_panel_path(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in PANEL_PATH_PREFIXES)


ROLE_CHOICES_FOR_UI: list[dict[str, str]] = [
    {
        'value': MailRole.FULL_ACCESS,
        'label': 'Süper Yönetici',
        'description': 'Mail sunucusu paneli + webmail; tüm ayarlar ve kullanıcı yönetimi.',
    },
    {
        'value': MailRole.WEBMAIL_USER,
        'label': 'Webmail Kullanıcısı',
        'description': 'Yalnızca webmail; mail sunucusu paneline erişim yok.',
    },
    {
        'value': MailRole.SEND_ONLY,
        'label': 'Yalnızca Gönderme',
        'description': 'Webmail; gelen kutusu kısıtlı, gönderim açık.',
    },
    {
        'value': MailRole.RECEIVE_ONLY,
        'label': 'Yalnızca Alma',
        'description': 'Webmail; gönderim kısıtlı, gelen kutusu açık.',
    },
    {
        'value': MailRole.EXTERNAL_BLOCK,
        'label': 'Şirket İçi',
        'description': 'Webmail; dış alanlara gönderim engelli.',
    },
]
