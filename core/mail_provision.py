"""Mail kutusu dizinleri ve Postfix/Dovecot otomatik hazırlık."""
from __future__ import annotations

import logging
import os
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

MAIL_UID = 5000
MAIL_GID = 5000
MAIL_SUBDIRS = (
    'cur', 'new', 'tmp',
    '.Sent/cur', '.Sent/new', '.Sent/tmp',
    '.Drafts/cur', '.Drafts/new', '.Drafts/tmp',
    '.Trash/cur', '.Trash/new', '.Trash/tmp',
)


def mail_root() -> Path:
    return Path(getattr(settings, 'POSTFIX_MAIL_ROOT', '/var/mail/vhosts'))


def account_maildir(account) -> Path:
    domain = account.domain.name if hasattr(account, 'domain') else str(account.domain)
    return mail_root() / domain / account.username


def ensure_maildir(account, *, chown: bool = True) -> Path:
    """Dovecot maildir++ alt yapısını oluştur."""
    base = account_maildir(account)
    for rel in MAIL_SUBDIRS:
        (base / rel).mkdir(parents=True, exist_ok=True)
    if chown:
        try:
            os.chown(base, MAIL_UID, MAIL_GID)
            for root, dirs, _files in os.walk(base):
                os.chown(root, MAIL_UID, MAIL_GID)
                for d in dirs:
                    os.chown(os.path.join(root, d), MAIL_UID, MAIL_GID)
        except (OSError, KeyError) as exc:
            logger.debug('maildir chown atlandı: %s', exc)
    return base


def provision_mail_account(account) -> dict:
    """Tek hesap: maildir + (isteğe bağlı) postfix reload."""
    if not account.is_active:
        return {'email': account.email, 'skipped': True}
    path = ensure_maildir(account)
    reload_postfix()
    return {'email': account.email, 'maildir': str(path)}


def provision_all_active_accounts() -> dict:
    from core.models import MailAccount

    results = []
    for account in MailAccount.objects.filter(is_active=True).select_related('domain'):
        try:
            results.append(provision_mail_account(account))
        except Exception as exc:
            logger.warning('Provision %s: %s', account.email, exc)
            results.append({'email': account.email, 'error': str(exc)})
    reload_postfix()
    return {'provisioned': len(results), 'accounts': results}


def reload_postfix() -> None:
    """Postfix yapılandırmasını yenile (pgsql map anlık okunur; reload güvenli)."""
    try:
        import docker

        name = os.getenv('JIR_CONTAINER_POSTFIX', 'jir_postfix')
        client = docker.from_env()
        try:
            c = client.containers.get(name)
            code, _out = c.exec_run(['postfix', 'reload'])
            if code != 0:
                c.exec_run(['sh', '/docker-init.d/10-jirmail-inbound.sh'])
                c.exec_run(['sh', '/docker-init.d/31-jirmail-transport-maps.sh'])
        finally:
            client.close()
    except Exception as exc:
        logger.debug('postfix reload atlandı (docker yok): %s', exc)
