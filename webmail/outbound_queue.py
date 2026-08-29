"""Arka planda SMTP gönderim kuyruğu."""
from __future__ import annotations

import logging
import os
from typing import Any

from django.conf import settings

from jir_core.session_secrets import encrypt_secret
from webmail.models import MailOutboundLog
from webmail.recipients import parse_recipient_list

logger = logging.getLogger(__name__)


def _outbound_attach_dir(outbound_id: int) -> str:
    base = getattr(settings, 'MEDIA_ROOT', None) or os.path.join(settings.BASE_DIR, 'media')
    path = os.path.join(str(base), 'outbound_queue', str(outbound_id))
    os.makedirs(path, exist_ok=True)
    return path


def save_outbound_attachments(outbound_id: int, files) -> list[dict]:
    """Yüklenen dosyaları geçici dizine kaydet; task metadata döner."""
    meta = []
    dest_root = _outbound_attach_dir(outbound_id)
    for idx, f in enumerate(files):
        safe_name = (getattr(f, 'name', None) or f'file-{idx}').replace('/', '_').replace('\\', '_')
        path = os.path.join(dest_root, safe_name)
        with open(path, 'wb') as out:
            for chunk in f.chunks():
                out.write(chunk)
        meta.append({
            'filename': safe_name,
            'mime_type': getattr(f, 'content_type', None) or 'application/octet-stream',
            'path': path,
        })
    return meta


def cleanup_outbound_attachments(outbound_id: int) -> None:
    import shutil

    base = getattr(settings, 'MEDIA_ROOT', None) or os.path.join(settings.BASE_DIR, 'media')
    path = os.path.join(str(base), 'outbound_queue', str(outbound_id))
    if os.path.isdir(path):
        try:
            shutil.rmtree(path, ignore_errors=True)
        except Exception:
            pass


def queue_outbound_send(
    account,
    password: str,
    *,
    to: str | list[str],
    subject: str,
    body_text: str = '',
    body_html: str = '',
    cc: str | list[str] | None = None,
    bcc: str | list[str] | None = None,
    attachments_meta: list[dict] | None = None,
) -> dict[str, Any]:
    """MailOutboundLog oluşturur ve Celery gönderim task'ını kuyruğa alır."""
    if isinstance(to, str):
        to_list = parse_recipient_list(to)
    else:
        to_list = list(to)
    cc_list = parse_recipient_list(cc) if cc else None
    bcc_list = parse_recipient_list(bcc) if bcc else None

    snippet = (body_text or body_html or '')[:480]
    log_row = MailOutboundLog.objects.create(
        account=account,
        to_addr=', '.join(to_list),
        subject=subject,
        snippet=snippet,
        status=MailOutboundLog.STATUS_PENDING,
    )

    payload = {
        'outbound_id': log_row.id,
        'password_enc': encrypt_secret(password),
        'to': to_list,
        'subject': subject,
        'body_text': body_text,
        'body_html': body_html,
        'cc': cc_list,
        'bcc': bcc_list,
        'attachments_meta': attachments_meta or [],
    }

    try:
        from webmail.tasks import send_mail_async

        send_mail_async.delay(**payload)
        queued = True
    except Exception as exc:
        logger.warning('Celery kuyruk hatası, senkron gönderim: %s', exc)
        from webmail.tasks import send_mail_async

        result = send_mail_async(**payload)
        queued = False
        if result.get('success'):
            return {
                'success': True,
                'queued': False,
                'outbound_id': log_row.id,
                'message': result.get('message') or 'Mesaj gönderildi.',
                'message_id': result.get('message_id'),
            }
        return {
            'success': False,
            'queued': False,
            'outbound_id': log_row.id,
            'message': result.get('message') or 'Gönderilemedi.',
        }

    return {
        'success': True,
        'queued': queued,
        'outbound_id': log_row.id,
        'message': 'Mesaj arka planda gönderiliyor.',
    }
