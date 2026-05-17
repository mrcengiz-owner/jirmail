"""Postfix (boky) — gelen posta + gönderim ortam değişkenleri."""
from __future__ import annotations

import os


def postfix_boky_base_environment(mail_domain: str, mail_hostname: str) -> dict[str, str]:
    """boky/postfix: gönderen kısıtı kapalı, alıcı (MX) modu."""
    domain = (mail_domain or os.getenv('MAIL_DOMAIN') or 'mail.local').strip()
    hostname = (mail_hostname or os.getenv('MAIL_HOSTNAME') or f'mail.{domain}').strip()
    return {
        'ALLOW_EMPTY_SENDER_DOMAINS': '1',
        # Alıcı kısıtı modu: boş gönderen listesi (dış MTA'lar @domain adresine teslim edebilir)
        'ALLOWED_SENDER_DOMAINS': '',
        'HOSTNAME': hostname,
        'POSTFIX_myhostname': hostname,
        'POSTFIX_mynetworks': '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16',
        'MAIL_DOMAIN': domain,
    }


def postfix_db_environment() -> dict[str, str]:
    """Init script: Postgres'ten virtual_mailbox_maps üretir."""
    return {
        'DB_HOST': os.getenv('DB_HOST', 'postgres'),
        'DB_PORT': os.getenv('DB_PORT', '5432'),
        'DB_NAME': os.getenv('POSTGRES_DB', os.getenv('DB_NAME', 'jir_mail_prod')),
        'DB_USER': os.getenv('POSTGRES_USER', os.getenv('DB_USER', 'postgres')),
        'DB_PASS': os.getenv('POSTGRES_PASSWORD', os.getenv('DB_PASS', '')),
    }
