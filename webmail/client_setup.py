"""Webmail — üçüncü parti istemci (iOS, Thunderbird vb.) kurulum bilgisi."""
from __future__ import annotations

import os
from typing import Any

from django.conf import settings

_INTERNAL_MAIL_HOSTS = frozenset({
    'postfix', 'dovecot', 'localhost', '127.0.0.1',
    'jir_postfix', 'jir_dovecot', 'postgres', 'redis', 'django',
})


def _is_public_host(host: str) -> bool:
    h = (host or '').strip().lower()
    if not h or h in _INTERNAL_MAIL_HOSTS:
        return False
    if h.endswith('.internal') or h.endswith('.local'):
        return False
    return True


def resolve_public_mail_host(*, account_email: str = '') -> str:
    """Telefon / Thunderbird için dışarıdan erişilebilir sunucu adı."""
    candidates: list[str] = []

    for key in ('MAIL_HOSTNAME', 'PUBLIC_MAIL_HOST'):
        v = (os.getenv(key) or '').strip()
        if v:
            candidates.append(v)

    try:
        from installer.mail_connectivity import mail_endpoints_from_system_config

        ep = mail_endpoints_from_system_config()
        for key in ('public_mail_host', 'mail_hostname', 'smtp_host_public'):
            v = (ep.get(key) or '').strip()
            if v:
                candidates.append(v)
    except Exception:
        pass

    try:
        from saas.models import SystemConfig

        conf = SystemConfig.objects.only('installation_log').first()
        if conf and isinstance(conf.installation_log, dict):
            for key in ('mail_hostname', 'public_mail_host'):
                v = (conf.installation_log.get(key) or '').strip()
                if v:
                    candidates.append(v)
    except Exception:
        pass

    mail_domain = (os.getenv('MAIL_DOMAIN') or '').strip()
    if mail_domain:
        candidates.append(f'mail.{mail_domain.lstrip("mail.")}')

    if '@' in (account_email or ''):
        dom = account_email.rsplit('@', 1)[-1].strip().lower()
        if dom and dom not in _INTERNAL_MAIL_HOSTS:
            candidates.append(f'mail.{dom}')

    for c in candidates:
        if _is_public_host(c):
            return c

    # Son çare: kurulum log / panel URL
    public_url = (os.getenv('PUBLIC_URL') or '').strip()
    if public_url.startswith('https://'):
        host = public_url[8:].split('/')[0].strip()
        if _is_public_host(host):
            return host

    return candidates[0] if candidates else 'mail.example.com'


def build_client_setup(*, account_email: str) -> dict[str, Any]:
    """Hesap bazlı IMAP/SMTP + platform rehberleri."""
    email = (account_email or '').strip()
    host = resolve_public_mail_host(account_email=email)
    imap_port = int(getattr(settings, 'IMAP_PORT', 993) or 993)
    smtp_port = int(getattr(settings, 'SMTP_PORT', 587) or 587)

    imap = {
        'host': host,
        'port': imap_port,
        'security': 'SSL/TLS',
        'username': email,
    }
    smtp = {
        'host': host,
        'port': smtp_port,
        'security': 'STARTTLS',
        'username': email,
        'auth_required': True,
    }

    pwd_hint = (
        'Webmail girişinde kullandığınız posta hesabı parolası. '
        'Panelden hesap oluşturulurken belirlenir; webmail oturum parolası ile aynıdır.'
    )

    def steps(*lines: str) -> list[str]:
        return [ln.format(host=host, email=email, imap_port=imap_port, smtp_port=smtp_port) for ln in lines]

    clients = [
        {
            'id': 'ios',
            'name': 'iPhone / iPad (Mail)',
            'icon': 'phone_iphone',
            'steps': steps(
                'Ayarlar → Uygulamalar → Mail → Mail Hesapları → Hesap Ekle → Diğer → Mail Hesabı Ekle.',
                'Ad: istediğiniz görünen ad · E-posta: {email}',
                'Kullanıcı adı: {email} · Parola: posta hesabı parolanız.',
                'IMAP: Sunucu {host} · Port {imap_port} · SSL açık.',
                'SMTP: Sunucu {host} · Port {smtp_port} · SSL kapalı, STARTTLS / TLS kullan açık.',
                'Kaydet → IMAP ve SMTP doğrulaması başarılı olmalı.',
            ),
        },
        {
            'id': 'android',
            'name': 'Android (Gmail uygulaması)',
            'icon': 'android',
            'steps': steps(
                'Gmail → Profil → E-posta ekle → Diğer → IMAP.',
                'E-posta: {email} · Parola: posta hesabı parolanız.',
                'Gelen sunucu (IMAP): {host} · Port {imap_port} · Güvenlik SSL/TLS.',
                'Giden sunucu (SMTP): {host} · Port {smtp_port} · Güvenlik STARTTLS · Kimlik doğrulama açık.',
                'Kullanıcı adı her iki sunucu için tam adres: {email}.',
            ),
        },
        {
            'id': 'thunderbird',
            'name': 'Mozilla Thunderbird',
            'icon': 'mail',
            'steps': steps(
                'Hesap Ayarları → Hesap Eylemleri → Mail Hesabı Ekle.',
                'Tam e-posta: {email} · Parola: posta hesabı parolanız → Devam.',
                'Manuel yapılandırma seçin: IMAP, sunucu {host}, port {imap_port}, SSL/TLS.',
                'Giden (SMTP): {host}, port {smtp_port}, STARTTLS, kimlik doğrulama normal parola.',
                'Kullanıcı adı: {email} (gelen ve giden).',
            ),
        },
        {
            'id': 'outlook',
            'name': 'Microsoft Outlook (masaüstü)',
            'icon': 'desktop_windows',
            'steps': steps(
                'Dosya → Hesap Ekle → Manuel kurulum → POP veya IMAP.',
                'Hesap türü: IMAP · Gelen: {host} · Port {imap_port} · Şifreleme SSL/TLS.',
                'Giden (SMTP): {host} · Port {smtp_port} · Şifreleme STARTTLS.',
                'Oturum açma: {email} · Parola: posta hesabı parolanız.',
                '“Giden sunucum (SMTP) kimlik doğrulaması gerektirir” işaretli olsun.',
            ),
        },
        {
            'id': 'windows',
            'name': 'Windows Mail / Outlook (UWP)',
            'icon': 'laptop_windows',
            'steps': steps(
                'Mail uygulaması → Ayarlar → Hesaplar → Ekle → Gelişmiş kurulum → İnternet e-postası.',
                'E-posta: {email} · Kullanıcı adı: {email} · Parola: posta hesabı parolanız.',
                'Gelen e-posta sunucusu IMAP: {host} · Port {imap_port} · SSL gerekli.',
                'Giden SMTP: {host} · Port {smtp_port} · STARTTLS · Kimlik doğrulama açık.',
            ),
        },
        {
            'id': 'generic',
            'name': 'Diğer IMAP istemcileri',
            'icon': 'settings',
            'steps': steps(
                'Hesap türü: IMAP (POP3 kullanmayın).',
                'Gelen: {host}:{imap_port} — SSL/TLS veya IMAPS.',
                'Giden: {host}:{smtp_port} — STARTTLS (587); port 465 kullanıyorsanız SSL modunu istemciye göre ayarlayın.',
                'Kullanıcı adı: tam e-posta {email} · Kimlik doğrulama: parola.',
                'Webmail adresi tarayıcı içindir; bu ayarlar telefon/tablet/masaüstü uygulamaları içindir.',
            ),
        },
    ]

    return {
        'email': email,
        'username': email,
        'password_hint': pwd_hint,
        'mail_host': host,
        'imap': imap,
        'smtp': smtp,
        'webmail_url_hint': (os.getenv('PUBLIC_URL') or '').strip() or None,
        'dns_hints': [
            f'{host} için DNS kaydı doğrudan sunucu IP’nize işaret etmeli (A kaydı).',
            'Cloudflare kullanıyorsanız mail kaydında turuncu bulut (proxy) KAPALI olmalı — '
            'yalnızca gri bulut (DNS only). Proxy açıkken 993/587 portları çalışmaz.',
            'VPS güvenlik duvarında 993 (IMAP) ve 587 (SMTP) gelen bağlantılara açık olmalı.',
        ],
        'clients': clients,
    }
