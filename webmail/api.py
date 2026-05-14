"""Webmail django-ninja router.

Endpoint'ler:
    GET    /api/mail/folders                       klasör listesi
    GET    /api/mail/messages                      metadata sayfalı
    GET    /api/mail/messages/{uid}/body           tek mesajın body'si
    POST   /api/mail/send                          SMTP submission
    PATCH  /api/mail/messages/{uid}/flags          read/star
    POST   /api/mail/messages/{uid}/move           klasöre taşı
    DELETE /api/mail/messages/{uid}                sil
    POST   /api/mail/sync                          manuel folder sync
    GET    /api/mail/stream                        SSE yeni mail push
"""
from typing import Optional

from django.http import HttpRequest
from ninja import Router, Schema

from core.models import MailAccount
from .imap_client import (
    delete_message, fetch_message_body, move_message, set_flag, sync_folder_metadata,
)
from .models import MailFolder, MailMessageCache
from .smtp_client import send_mail
from .sse import webmail_sse_response


router = Router()


def _get_account_and_password(request: HttpRequest):
    """Session'dan giriş yapan mail hesabını ve şifresini al."""
    account_id = request.session.get('account_id')
    password = request.session.get('mail_password', '')
    if not account_id or not password:
        return None, ''
    return MailAccount.objects.filter(id=account_id).first(), password


@router.get('/folders', summary='Folder listesi')
def list_folders(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    folders = MailFolder.objects.filter(account=account)
    return {
        'success': True,
        'folders': [
            {
                'name': f.name,
                'display_name': f.display_name or f.name,
                'total': f.total,
                'unread': f.unread,
                'last_synced': f.last_synced.isoformat() if f.last_synced else None,
            }
            for f in folders
        ],
    }


@router.get('/messages', summary='Mesaj listesi (metadata, sayfalı)')
def list_messages(request: HttpRequest, folder: str = 'INBOX', page: int = 1, page_size: int = 50, q: str = ''):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    folder_obj = MailFolder.objects.filter(account=account, name=folder).first()
    if not folder_obj:
        return {'success': True, 'folder': folder, 'messages': [], 'total': 0, 'page': page}

    qs = MailMessageCache.objects.filter(folder=folder_obj, is_deleted=False)
    if q:
        qs = qs.filter(subject__icontains=q) | qs.filter(from_addr__icontains=q)

    total = qs.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    start = (page - 1) * page_size
    end = start + page_size

    messages = [
        {
            'uid': m.uid,
            'subject': m.subject,
            'from': m.from_addr,
            'from_name': m.from_name,
            'to': m.to_addr,
            'date': m.date.isoformat() if m.date else None,
            'is_seen': m.is_seen,
            'is_flagged': m.is_flagged,
            'is_answered': m.is_answered,
            'has_attachments': m.has_attachments,
            'snippet': m.snippet,
            'size': m.raw_size,
        }
        for m in qs[start:end]
    ]

    return {
        'success': True,
        'folder': folder,
        'page': page,
        'page_size': page_size,
        'total': total,
        'messages': messages,
    }


@router.get('/messages/{uid}/body', summary='Tek mesajın body\'si')
def message_body(request: HttpRequest, uid: int, folder: str = 'INBOX'):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    try:
        result = fetch_message_body(account, password, folder, uid)
        return {'success': True, 'folder': folder, 'uid': uid, **result}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


class SendMailSchema(Schema):
    to: str
    subject: str
    body_text: str = ''
    body_html: str = ''
    cc: str = ''
    bcc: str = ''


@router.post('/send', summary='Mail gönder')
def send(request: HttpRequest, data: SendMailSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    to_list = [x.strip() for x in data.to.split(',') if x.strip()]
    cc_list = [x.strip() for x in data.cc.split(',') if x.strip()] if data.cc else None
    bcc_list = [x.strip() for x in data.bcc.split(',') if x.strip()] if data.bcc else None

    result = send_mail(
        account, password,
        to=to_list, subject=data.subject,
        body_text=data.body_text, body_html=data.body_html,
        cc=cc_list, bcc=bcc_list,
    )
    return result


class FlagPatchSchema(Schema):
    folder: str = 'INBOX'
    seen: Optional[bool] = None
    flagged: Optional[bool] = None


@router.patch('/messages/{uid}/flags', summary='Read/Star güncelle')
def patch_flags(request: HttpRequest, uid: int, data: FlagPatchSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    try:
        if data.seen is not None:
            set_flag(account, password, data.folder, uid, '\\Seen', add=data.seen)
        if data.flagged is not None:
            set_flag(account, password, data.folder, uid, '\\Flagged', add=data.flagged)

        folder_obj = MailFolder.objects.filter(account=account, name=data.folder).first()
        if folder_obj:
            msg = MailMessageCache.objects.filter(folder=folder_obj, uid=uid).first()
            if msg:
                if data.seen is not None:
                    msg.is_seen = data.seen
                if data.flagged is not None:
                    msg.is_flagged = data.flagged
                msg.save(update_fields=['is_seen', 'is_flagged'])
        return {'success': True}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


class MoveSchema(Schema):
    folder: str = 'INBOX'
    target: str


@router.post('/messages/{uid}/move', summary='Mesajı klasöre taşı')
def move(request: HttpRequest, uid: int, data: MoveSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    try:
        move_message(account, password, data.folder, uid, data.target)
        return {'success': True}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


@router.delete('/messages/{uid}', summary='Mesajı sil')
def delete(request: HttpRequest, uid: int, folder: str = 'INBOX'):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    try:
        delete_message(account, password, folder, uid)
        folder_obj = MailFolder.objects.filter(account=account, name=folder).first()
        if folder_obj:
            MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_deleted=True)
        return {'success': True}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


class SyncSchema(Schema):
    folder: str = 'INBOX'
    limit: int = 200


@router.post('/sync', summary='Folder metadata sync')
def sync(request: HttpRequest, data: SyncSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    try:
        result = sync_folder_metadata(account, password, data.folder, limit=data.limit)
        return {'success': True, **result}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


def mail_stream(request: HttpRequest):
    """SSE endpoint — yeni mail push."""
    account_id = request.session.get('account_id')
    if not account_id:
        from django.http import JsonResponse
        return JsonResponse({'success': False, 'message': 'Oturum yok'}, status=403)
    return webmail_sse_response(int(account_id))
