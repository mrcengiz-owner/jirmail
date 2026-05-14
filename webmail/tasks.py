"""Webmail için Celery task'ları.

- sync_folder: kullanıcının folder metadata'sını DB'ye senkronlar
- imap_idle_listener: aktif hesaplar için IMAP IDLE bağlantısı tutar (uzun yaşar)
"""
from __future__ import annotations

import logging
import time

from celery import shared_task

from .imap_client import imap_connection, sync_folder_metadata
from .sse import publish_new_mail


logger = logging.getLogger(__name__)


@shared_task(name='webmail.sync_folder')
def sync_folder(account_id: int, password: str, folder_name: str = 'INBOX', limit: int = 200):
    from core.models import MailAccount

    account = MailAccount.objects.filter(id=account_id).first()
    if not account:
        return {'success': False, 'message': 'Account bulunamadı'}

    try:
        result = sync_folder_metadata(account, password, folder_name, limit=limit)
        return {'success': True, **result}
    except Exception as exc:
        logger.exception('Sync folder failed: %s', exc)
        return {'success': False, 'message': str(exc)}


@shared_task(name='webmail.imap_idle_listener', bind=True)
def imap_idle_listener(self, account_id: int, password: str, folder_name: str = 'INBOX',
                       idle_timeout: int = 600):
    """IMAP IDLE bağlantısını uzun süre açık tutar; yeni UID gelince DB'ye yazıp SSE push eder."""
    from core.models import MailAccount

    account = MailAccount.objects.filter(id=account_id).first()
    if not account:
        return {'success': False, 'message': 'Account bulunamadı'}

    try:
        with imap_connection(account, password) as client:
            client.select_folder(folder_name)
            client.idle()
            logger.info('IDLE started for %s/%s', account.email, folder_name)
            start = time.time()
            try:
                while time.time() - start < idle_timeout:
                    responses = client.idle_check(timeout=30)
                    if responses:
                        client.idle_done()
                        sync_folder_metadata(account, password, folder_name, limit=20)
                        publish_new_mail(account_id, {'folder': folder_name})
                        client.idle()
            finally:
                try:
                    client.idle_done()
                except Exception:
                    pass
        return {'success': True}
    except Exception as exc:
        logger.exception('IDLE failed: %s', exc)
        return {'success': False, 'message': str(exc)}
