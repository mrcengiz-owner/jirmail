"""Webmail için Celery task'ları.

- sync_folder: kullanıcının folder metadata'sını DB'ye senkronlar
- imap_idle_listener: aktif hesaplar için IMAP IDLE bağlantısı tutar (uzun yaşar)
"""
from __future__ import annotations

import logging
import time
from datetime import timedelta

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


@shared_task(name='webmail.send_mail_async')
def send_mail_async(
    outbound_id: int,
    password_enc: str,
    to: list[str],
    subject: str,
    body_text: str = '',
    body_html: str = '',
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    attachments_meta: list[dict] | None = None,
):
    """SMTP gönderimini arka planda tamamlar; SSE ile durum bildirir."""
    from jir_core.session_secrets import decrypt_secret
    from webmail.models import MailOutboundLog
    from webmail.outbound_queue import cleanup_outbound_attachments
    from webmail.smtp_client import send_mail
    from webmail.sse import publish_outbound_status

    log_row = MailOutboundLog.objects.select_related('account', 'account__domain').filter(
        pk=outbound_id,
    ).first()
    if not log_row:
        return {'success': False, 'message': 'Outbound kaydı bulunamadı'}

    account = log_row.account
    account_id = account.id

    try:
        password = decrypt_secret(password_enc)
    except Exception:
        log_row.status = MailOutboundLog.STATUS_FAILED
        log_row.error_message = 'Oturum parolası çözülemedi — yeniden giriş gerekir.'
        log_row.save(update_fields=['status', 'error_message'])
        publish_outbound_status(account_id, outbound_id, 'failed', log_row.error_message)
        return {'success': False, 'message': log_row.error_message}

    attachments = None
    if attachments_meta:
        attachments = []
        for item in attachments_meta:
            path = item.get('path') or ''
            if not path or not __import__('os').path.isfile(path):
                continue
            with open(path, 'rb') as fh:
                attachments.append({
                    'filename': item.get('filename') or 'attachment',
                    'mime_type': item.get('mime_type') or 'application/octet-stream',
                    'content': fh.read(),
                })

    try:
        from management.outbound_autoconfig import ensure_outbound_delivery

        ensure_outbound_delivery(fix=True, full_heal=False)
    except Exception:
        pass

    try:
        result = send_mail(
            account,
            password,
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            cc=cc,
            bcc=bcc,
            attachments=attachments or None,
        )
    except Exception as exc:
        logger.exception('send_mail_async outbound=%s', outbound_id)
        log_row.status = MailOutboundLog.STATUS_FAILED
        log_row.error_message = str(exc)[:2000]
        log_row.save(update_fields=['status', 'error_message'])
        cleanup_outbound_attachments(outbound_id)
        publish_outbound_status(account_id, outbound_id, 'failed', log_row.error_message)
        return {'success': False, 'message': log_row.error_message}

    cleanup_outbound_attachments(outbound_id)

    if result.get('success'):
        log_row.status = MailOutboundLog.STATUS_SENT
        log_row.message_id = (result.get('message_id') or '')[:512]
        log_row.error_message = ''
        log_row.save(update_fields=['status', 'message_id', 'error_message'])
        publish_outbound_status(account_id, outbound_id, 'sent', result.get('message') or '')
        return {'success': True, 'outbound_id': outbound_id, 'message_id': result.get('message_id')}

    log_row.status = MailOutboundLog.STATUS_FAILED
    log_row.error_message = (result.get('message') or 'Gönderilemedi')[:2000]
    log_row.save(update_fields=['status', 'error_message'])
    publish_outbound_status(account_id, outbound_id, 'failed', log_row.error_message)
    return {'success': False, 'message': log_row.error_message}


@shared_task(name='webmail.run_ai_task')
def run_ai_task(task_id: int, password_enc: str = ''):
    """Kullanıcı tarafından verilen AI görevini arka planda çalıştırır."""
    from jir_core.session_secrets import decrypt_secret
    from webmail.ai.service import run_stored_ai_task
    from webmail.models import MailAiTask
    from webmail.sse import publish_ai_task_status

    row = MailAiTask.objects.select_related('account', 'account__domain').filter(pk=task_id).first()
    if not row:
        return {'success': False, 'message': 'Görev bulunamadı'}

    row.status = MailAiTask.STATUS_RUNNING
    row.save(update_fields=['status'])

    password = ''
    if password_enc:
        try:
            password = decrypt_secret(password_enc)
        except Exception:
            pass

    try:
        result = run_stored_ai_task(row, password=password)
        row.status = MailAiTask.STATUS_DONE if result.get('success') else MailAiTask.STATUS_FAILED
        row.result = result
        row.error_message = '' if result.get('success') else (result.get('message') or '')[:2000]
        row.finished_at = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
        row.save(update_fields=['status', 'result', 'error_message', 'finished_at'])
        publish_ai_task_status(row.account_id, row.id, row.status, result)
        return result
    except Exception as exc:
        logger.exception('run_ai_task %s', task_id)
        row.status = MailAiTask.STATUS_FAILED
        row.error_message = str(exc)[:2000]
        row.finished_at = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
        row.save(update_fields=['status', 'error_message', 'finished_at'])
        publish_ai_task_status(row.account_id, row.id, row.status, {'message': str(exc)})
        return {'success': False, 'message': str(exc)}


@shared_task(name='webmail.process_scheduled_mail')
def process_scheduled_mail():
    from django.utils import timezone

    from webmail.models import ScheduledMail
    from webmail.smtp_client import send_mail

    now = timezone.now()
    pending = ScheduledMail.objects.filter(
        status=ScheduledMail.STATUS_PENDING,
        send_at__lte=now,
    ).select_related('account', 'account__domain')[:20]

    results = []
    for row in pending:
        account = row.account
        try:
            out = send_mail(
                account,
                '',
                to=[x.strip() for x in row.to_addr.split(',') if x.strip()],
                subject=row.subject,
                body_text=row.body_text,
                body_html=row.body_html,
            )
            if out.get('success'):
                row.status = ScheduledMail.STATUS_SENT
                row.sent_at = now
                row.error_message = ''
            else:
                row.status = ScheduledMail.STATUS_FAILED
                row.error_message = (out.get('message') or '')[:2000]
            row.save(update_fields=['status', 'sent_at', 'error_message'])
            results.append({'id': row.id, 'ok': out.get('success')})
        except Exception as exc:
            row.status = ScheduledMail.STATUS_FAILED
            row.error_message = str(exc)[:2000]
            row.save(update_fields=['status', 'error_message'])
            logger.exception('Scheduled mail %s failed', row.id)
    return {'processed': len(results), 'results': results}


@shared_task(name='webmail.ai_agent_cycle')
def ai_agent_cycle_task(
    account_id: int,
    password_enc: str = '',
    triage: bool = True,
    organize: bool = True,
    digest: bool = False,
):
    from jir_core.session_secrets import decrypt_secret
    from core.models import MailAccount
    from webmail.ai.agent import run_agent_cycle
    from webmail.credential_cache import get_cached_account_password

    account = MailAccount.objects.select_related('domain').filter(pk=account_id).first()
    if not account:
        return {'success': False, 'message': 'Hesap yok'}

    password = ''
    if password_enc:
        try:
            password = decrypt_secret(password_enc)
        except Exception:
            pass
    if not password:
        password = get_cached_account_password(account_id)
    if not password:
        return {'success': False, 'message': 'Parola önbelleği yok — webmail’e giriş yapın.'}

    try:
        return run_agent_cycle(
            account,
            password,
            triage=triage,
            organize=organize,
            digest=digest,
        )
    except Exception as exc:
        logger.exception('ai_agent_cycle %s', account_id)
        return {'success': False, 'message': str(exc)}


@shared_task(name='webmail.ai_agent_scheduled')
def ai_agent_scheduled():
    """Aktif oturumu olan hesaplarda periyodik triage/organize."""
    from jir_core.session_secrets import encrypt_secret
    from webmail.credential_cache import get_cached_account_password
    from webmail.models import MailAgentProfile

    queued = 0
    for profile in MailAgentProfile.objects.filter(
        mode__in=[MailAgentProfile.MODE_ASSIST, MailAgentProfile.MODE_AUTOPILOT],
        auto_triage=True,
    ).select_related('account', 'account__domain'):
        account = profile.account
        if not account.ai_available or not account.is_active:
            continue
        pwd = get_cached_account_password(account.id)
        if not pwd:
            continue
        try:
            ai_agent_cycle_task.delay(
                account.id,
                encrypt_secret(pwd),
                triage=True,
                organize=profile.auto_organize,
                digest=False,
            )
            queued += 1
        except Exception as exc:
            logger.warning('ai_agent_scheduled queue %s: %s', account.email, exc)
    return {'queued': queued}


@shared_task(name='webmail.ai_digest_scheduled')
def ai_digest_scheduled():
    """Digest saati gelen hesaplara özet üret."""
    from jir_core.session_secrets import encrypt_secret
    from webmail.credential_cache import get_cached_account_password
    from webmail.models import MailAgentProfile

    now = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
    hour = now.hour
    queued = 0
    for profile in MailAgentProfile.objects.filter(
        digest_enabled=True,
        mode__in=[MailAgentProfile.MODE_ASSIST, MailAgentProfile.MODE_AUTOPILOT],
    ).select_related('account', 'account__domain'):
        if profile.digest_hour != hour:
            continue
        if profile.last_digest_at and (now - profile.last_digest_at) < timedelta(hours=20):
            continue
        account = profile.account
        if not account.ai_available:
            continue
        pwd = get_cached_account_password(account.id)
        if not pwd:
            continue
        try:
            ai_agent_cycle_task.delay(
                account.id,
                encrypt_secret(pwd),
                triage=False,
                organize=False,
                digest=True,
            )
            queued += 1
        except Exception as exc:
            logger.warning('digest queue %s: %s', account.email, exc)
    return {'queued': queued}
