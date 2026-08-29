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
    POST   /api/mail/sync-all                      INBOX + Spam + Sent + Drafts + Trash sync
    GET    /api/mail/stream                        SSE yeni mail push
"""
from typing import Optional

from django.db import models
from django.http import HttpRequest
from ninja import Router, Schema

from core.models import MailAccount
from .imap_client import (
    delete_message, fetch_message_body, move_message, resolve_imap_folder, set_flag,
    sync_folder_metadata, sync_standard_folders,
)
from .models import MailFolder, MailMessageCache, MailOutboundLog
from .sender import purge_blocked_inbound_cache, sender_info_from_cache_row, should_block_inbound
from .recipients import parse_recipient_list
from .smtp_client import send_mail
from .sse import webmail_sse_response


router = Router()


def _imap_delivery_status(folder: str, msg: MailMessageCache) -> str:
    """Liste satırı için durum noktası: sent klasörü yeşil, gelen mavi/gri."""
    if folder.lower() in ('sent', 'sent messages', 'inbox.sent'):
        return 'sent'
    if not msg.is_seen:
        return 'unread'
    return 'read'


def _outbound_as_messages(account, *, limit: int = 50) -> list[dict]:
    """IMAP’ta henüz görünmeyen veya başarısız gönderim kayıtları."""
    rows = (
        MailOutboundLog.objects.filter(account=account)
        .filter(
            models.Q(status=MailOutboundLog.STATUS_PENDING)
            | models.Q(status=MailOutboundLog.STATUS_FAILED)
            | models.Q(status=MailOutboundLog.STATUS_DEFERRED)
        )
        .order_by('-created_at')[:limit]
    )
    out = []
    for row in rows:
        st = row.status
        if st == MailOutboundLog.STATUS_PENDING:
            delivery = 'pending'
        elif st == MailOutboundLog.STATUS_SENT:
            delivery = 'sent'
        elif st == MailOutboundLog.STATUS_DEFERRED:
            delivery = 'deferred'
        else:
            delivery = 'failed'
        out.append({
            'uid': -int(row.id),
            'subject': row.subject or '(konu yok)',
            'from': account.email,
            'from_name': account.username,
            'to': row.to_addr,
            'date': row.created_at.isoformat(),
            'is_seen': True,
            'is_flagged': False,
            'is_answered': False,
            'has_attachments': False,
            'snippet': row.snippet or '',
            'size': 0,
            'delivery_status': delivery,
            'source': 'outbound',
            'outbound_id': row.id,
        })
    return out


def _folder_is_inbound(folder: str) -> bool:
    from webmail.imap_client import is_spam_folder_name

    key = (folder or 'INBOX').strip()
    if key.upper() == 'INBOX' or key.upper().endswith('/INBOX'):
        return True
    return is_spam_folder_name(key)


def _message_to_api(m: MailMessageCache, account: MailAccount, folder: str) -> dict:
    inbound = _folder_is_inbound(folder)
    sender = sender_info_from_cache_row(m, account.email, is_inbound=inbound)
    return {
        'uid': m.uid,
        'subject': m.subject,
        'from': sender.get('display') or m.from_addr,
        'from_name': sender.get('from_name') or m.from_name,
        'from_addr': sender.get('from_email') or m.from_addr,
        'to': m.to_addr,
        'date': m.date.isoformat() if m.date else None,
        'is_seen': m.is_seen,
        'is_flagged': m.is_flagged,
        'is_answered': m.is_answered,
        'has_attachments': m.has_attachments,
        'snippet': m.snippet,
        'size': m.raw_size,
        'delivery_status': _imap_delivery_status(folder, m),
        'source': 'imap',
        'is_spoofed': bool(sender.get('is_spoofed')),
        'is_probable_scam': bool(sender.get('is_probable_scam')),
        'sender_warning': sender.get('warning'),
        'sender_real_email': sender.get('real_email'),
        'sender_reply_to': sender.get('reply_to'),
        'sender_return_path': sender.get('return_path'),
        'auth': sender.get('auth') or {},
        'ai_meta': m.ai_meta if isinstance(getattr(m, 'ai_meta', None), dict) else {},
    }


def _get_account_and_password(request: HttpRequest):
    """Session'dan giriş yapan mail hesabını ve (şifreli) parolasını al."""
    from jir_core.session_secrets import get_mail_password

    account_id = request.session.get('account_id')
    password = get_mail_password(request.session)
    if not account_id or not password:
        return None, ''
    account = MailAccount.objects.select_related('domain').filter(id=account_id).first()
    if account and password:
        try:
            from webmail.credential_cache import cache_account_password
            cache_account_password(int(account_id), password)
        except Exception:
            pass
    return account, password


@router.get('/folders', summary='Folder listesi')
def list_folders(request: HttpRequest):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    if password:
        try:
            from webmail.imap_client import sync_folders_from_imap
            sync_folders_from_imap(account, password)
        except Exception:
            pass

    from webmail.imap_client import folder_display_name, is_standard_folder_name

    folders = MailFolder.objects.filter(account=account).order_by('name')
    standard = []
    custom = []
    for f in folders:
        row = {
            'name': f.name,
            'display_name': f.display_name or folder_display_name(f.name),
            'total': f.total,
            'unread': f.unread,
            'last_synced': f.last_synced.isoformat() if f.last_synced else None,
            'kind': 'standard' if is_standard_folder_name(f.name) else 'custom',
        }
        if row['kind'] == 'custom':
            custom.append(row)
        else:
            standard.append(row)
    return {
        'success': True,
        'folders': standard + custom,
        'custom_folders': custom,
    }


class FolderCreateSchema(Schema):
    name: str
    display_name: Optional[str] = None


@router.post('/folders', summary='Yeni IMAP klasörü oluştur')
def create_folder(request: HttpRequest, data: FolderCreateSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok — yeniden giriş yapın.'}
    from webmail.imap_client import create_imap_folder, folder_display_name

    try:
        imap_name = create_imap_folder(account, password, data.name)
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}

    display = (data.display_name or folder_display_name(imap_name))[:255]
    row, _ = MailFolder.objects.update_or_create(
        account=account,
        name=imap_name,
        defaults={'display_name': display},
    )
    return {
        'success': True,
        'folder': {
            'name': row.name,
            'display_name': row.display_name,
            'total': row.total,
            'unread': row.unread,
            'kind': 'custom',
        },
    }


@router.delete('/folders', summary='Özel klasörü sil')
def delete_folder(request: HttpRequest, name: str = ''):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok — yeniden giriş yapın.'}
    folder_name = (name or request.GET.get('name') or '').strip()
    if not folder_name:
        return {'success': False, 'message': 'Klasör adı gerekli'}
    from webmail.imap_client import delete_imap_folder

    try:
        delete_imap_folder(account, password, folder_name)
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}
    return {'success': True, 'message': 'Klasör silindi'}


def _find_folder_row(account, folder: str):
    """DB'de klasör satırı — tam ad veya alias ile."""
    folder_obj = MailFolder.objects.filter(account=account, name=folder).first()
    if folder_obj:
        return folder_obj
    key = (folder or 'INBOX').lower().split('/')[-1].replace('.', '')
    from webmail.imap_client import FOLDER_ALIASES
    for candidate in FOLDER_ALIASES.get(key, [folder]):
        folder_obj = MailFolder.objects.filter(account=account, name=candidate).first()
        if folder_obj:
            return folder_obj
    return None


@router.get('/messages', summary='Mesaj listesi (metadata, sayfalı)')
def list_messages(request: HttpRequest, folder: str = 'INBOX', page: int = 1, page_size: int = 50, q: str = ''):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    folder_obj = _find_folder_row(account, folder)
    if password and folder_obj is None and not q and page == 1:
        try:
            imap_folder = resolve_imap_folder(account, password, folder)
            sync_folder_metadata(account, password, imap_folder, limit=200)
            folder_obj = _find_folder_row(account, folder) or MailFolder.objects.filter(
                account=account, name=imap_folder
            ).first()
        except Exception:
            pass

    if not folder_obj:
        if account and folder.lower() in ('sent', 'sent messages', 'inbox.sent'):
            outbound = _outbound_as_messages(account, limit=page_size)
            return {
                'success': True,
                'folder': folder,
                'page': page,
                'page_size': page_size,
                'total': len(outbound),
                'messages': outbound,
            }
        return {'success': True, 'folder': folder, 'messages': [], 'total': 0, 'page': page}

    qs = MailMessageCache.objects.filter(folder=folder_obj, is_deleted=False)
    if q:
        qs = qs.filter(
            models.Q(subject__icontains=q)
            | models.Q(from_addr__icontains=q)
            | models.Q(from_name__icontains=q)
            | models.Q(snippet__icontains=q)
        )

    if _folder_is_inbound(folder):
        qs = qs.exclude(sender_meta__is_spoofed=True).exclude(sender_meta__is_probable_scam=True)

    total = qs.count()
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    start = (page - 1) * page_size
    end = start + page_size

    messages = [_message_to_api(m, account, folder) for m in qs[start:end]]

    if account and folder.lower() in ('sent', 'sent messages', 'inbox.sent'):
        outbound = _outbound_as_messages(account, limit=page_size)
        messages = outbound + messages
        total += len(outbound)

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

    if uid < 0:
        row = MailOutboundLog.objects.filter(account=account, id=-uid).first()
        if not row:
            return {'success': False, 'message': 'Kayıt bulunamadı'}
        plain = row.snippet or ''
        if row.error_message:
            plain += '\n\n--- Hata ---\n' + row.error_message
        return {
            'success': True,
            'folder': folder,
            'uid': uid,
            'html': '',
            'plain': plain,
            'attachments': [],
        }

    try:
        result = fetch_message_body(account, password, folder, uid)
        sender = result.get('sender') or {}
        # Cache güncelle (sonraki liste görünümü için)
        folder_obj = _find_folder_row(account, folder)
        if folder_obj and sender:
            try:
                MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(
                    from_addr=sender.get('from_email', '')[:500],
                    from_name=(sender.get('from_name') or '')[:255],
                    sender_meta=sender,
                )
            except Exception:
                MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(
                    from_addr=sender.get('from_email', '')[:500],
                    from_name=(sender.get('from_name') or '')[:255],
                )
        out = {'success': True, 'folder': folder, 'uid': uid, **result}
        try:
            from webmail.send_validation import parse_bounce_report

            report = parse_bounce_report(result.get('html') or '', result.get('plain') or '')
            if report.get('is_bounce'):
                out['bounce_report'] = report
                out['bounce_summary'] = (
                    (report.get('recipient') or '') + ' — ' + (report.get('reason') or '')
                ).strip(' —')[:500]
        except Exception:
            pass
        return out
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


class SendMailSchema(Schema):
    to: str
    subject: str
    body_text: str = ''
    body_html: str = ''
    cc: str = ''
    bcc: str = ''
    background: bool = True


def _sanitize_send_result(result: dict) -> dict:
    """SMTP yanıtını JSON-safe hale getir (bytes vb. kaldır)."""
    if not isinstance(result, dict):
        return {'success': False, 'message': 'Geçersiz gönderim yanıtı'}
    safe = {}
    for key, val in result.items():
        if key == 'raw_message' or isinstance(val, (bytes, bytearray)):
            continue
        safe[key] = val
    return safe


@router.post('/send', summary='Mail gönder')
def send(request: HttpRequest, data: SendMailSchema):
    import logging
    log = logging.getLogger(__name__)
    try:
        account, password = _get_account_and_password(request)
        if not account:
            return {'success': False, 'message': 'Oturum yok'}

        if not password:
            return {
                'success': False,
                'message': (
                    'Oturumda mail parolası yok. Çıkış yapıp webmail’e tekrar giriş yapın '
                    '(IMAP/Sent için parola gerekir).'
                ),
            }

        from webmail.send_validation import validate_outbound_recipients

        check = validate_outbound_recipients(account, data.to, data.cc, data.bcc)
        if not check['ok']:
            return {'success': False, 'message': check['message'], 'invalid': check.get('invalid', [])}

        try:
            from management.outbound_autoconfig import ensure_outbound_delivery

            ensure_outbound_delivery(fix=True, full_heal=False)
        except Exception as exc:
            log.debug('ensure_outbound_delivery: %s', exc)

        to_list = parse_recipient_list(data.to)
        cc_list = parse_recipient_list(data.cc) or None
        bcc_list = parse_recipient_list(data.bcc) or None

        snippet = (data.body_text or data.body_html or '')[:480]
        log_row = None
        try:
            log_row = MailOutboundLog.objects.create(
                account=account,
                to_addr=', '.join(to_list),
                subject=data.subject,
                snippet=snippet,
                status=MailOutboundLog.STATUS_PENDING,
            )
        except Exception as exc:
            log.warning('MailOutboundLog kaydı atlandı: %s', exc)

        if data.background:
            from webmail.outbound_queue import queue_outbound_send

            if log_row:
                log_row.delete()
            out = queue_outbound_send(
                account,
                password,
                to=data.to,
                subject=data.subject,
                body_text=data.body_text,
                body_html=data.body_html,
                cc=data.cc,
                bcc=data.bcc,
            )
            for w in check.get('warnings') or []:
                out.setdefault('warnings', []).append(w)
            return out

        result = send_mail(
            account, password,
            to=to_list, subject=data.subject,
            body_text=data.body_text, body_html=data.body_html,
            cc=cc_list, bcc=bcc_list,
        )

        if result.get('success'):
            if log_row:
                log_row.status = MailOutboundLog.STATUS_SENT
                log_row.message_id = (result.get('message_id') or '')[:512]
                log_row.save(update_fields=['status', 'message_id'])
                result['outbound_id'] = log_row.id
            warn = result.get('sent_imap_warning') or ''
            if warn and 'AUTHENTICATIONFAILED' in warn.upper():
                result['message'] = (
                    'Mesaj Postfix tarafından kabul edildi ancak Dovecot IMAP kimlik doğrulaması başarısız. '
                    'Çıkış yapıp aynı parola ile tekrar giriş yapın.'
                )
            elif warn:
                result['message'] = (
                    'Mesaj gönderildi. Gönderilen klasörüne kopyalanamadı — klasörü yenileyin.'
                )
            for w in check.get('warnings') or []:
                result.setdefault('warnings', []).append(w)
            if check.get('warnings') and not result.get('message'):
                result['message'] = 'Mesaj sunucuya iletildi.'
        else:
            if log_row:
                log_row.status = MailOutboundLog.STATUS_FAILED
                log_row.error_message = (result.get('message') or '')[:2000]
                log_row.save(update_fields=['status', 'error_message'])

        return _sanitize_send_result(result)
    except Exception as exc:
        log.exception('POST /api/mail/send')
        return {'success': False, 'message': f'Gönderim hatası: {exc}'}


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
        src = resolve_imap_folder(account, password, data.folder)
        target = resolve_imap_folder(account, password, data.target)
        move_message(account, password, src, uid, target)
        return {'success': True}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


class BulkActionSchema(Schema):
    folder: str = 'INBOX'
    uids: list[int]
    action: str  # seen | unseen | delete | star | unstar | spam | not_spam


@router.post('/messages/bulk', summary='Toplu işlem')
def bulk_messages(request: HttpRequest, data: BulkActionSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not data.uids:
        return {'success': False, 'message': 'UID listesi boş'}

    imap_folder = resolve_imap_folder(account, password, data.folder)
    folder_obj = _find_folder_row(account, data.folder) or MailFolder.objects.filter(
        account=account, name=imap_folder
    ).first()
    ok = 0
    errors = []
    for uid in data.uids:
        if uid < 0:
            continue
        try:
            if data.action == 'seen':
                set_flag(account, password, imap_folder, uid, '\\Seen', add=True)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_seen=True)
            elif data.action == 'unseen':
                set_flag(account, password, imap_folder, uid, '\\Seen', add=False)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_seen=False)
            elif data.action == 'star':
                set_flag(account, password, imap_folder, uid, '\\Flagged', add=True)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_flagged=True)
            elif data.action == 'unstar':
                set_flag(account, password, imap_folder, uid, '\\Flagged', add=False)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_flagged=False)
            elif data.action == 'delete':
                delete_message(account, password, imap_folder, uid)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_deleted=True)
            elif data.action == 'spam':
                target = resolve_imap_folder(account, password, 'Junk')
                move_message(account, password, imap_folder, uid, target)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_deleted=True)
            elif data.action == 'not_spam':
                target = resolve_imap_folder(account, password, 'INBOX')
                move_message(account, password, imap_folder, uid, target)
                if folder_obj:
                    MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_deleted=True)
            else:
                return {'success': False, 'message': f'Bilinmeyen işlem: {data.action}'}
            ok += 1
        except Exception as exc:
            errors.append({'uid': uid, 'error': str(exc)})
    return {'success': True, 'processed': ok, 'errors': errors}


class SaveDraftSchema(Schema):
    to: str = ''
    cc: str = ''
    subject: str = ''
    body_text: str = ''
    body_html: str = ''
    draft_uid: Optional[int] = None


@router.post('/drafts', summary='Taslak kaydet')
def save_draft(request: HttpRequest, data: SaveDraftSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturumda parola yok — yeniden giriş yapın.'}

    try:
        from webmail.imap_client import (
            append_message_to_drafts,
            build_mime_draft,
            remove_draft_message,
            sync_folder_metadata,
        )

        if data.draft_uid and data.draft_uid > 0:
            try:
                remove_draft_message(account, password, data.draft_uid)
            except Exception:
                pass

        raw = build_mime_draft(
            account,
            to=data.to,
            cc=data.cc,
            subject=data.subject,
            body_text=data.body_text,
            body_html=data.body_html,
        )
        folder = append_message_to_drafts(account, password, raw)
        sync_folder_metadata(account, password, folder, limit=50)
        return {'success': True, 'message': 'Taslak kaydedildi', 'folder': folder}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}


def _outbound_delivery_report() -> dict:
    """Dış posta çıkışı (port 25 / relay) — tanılama."""
    try:
        from management.outbound_autoconfig import ensure_outbound_delivery, probe_postfix_recipient_routing
        from management.outbound_connectivity import check_outbound_smtp

        ensure_outbound_delivery(fix=True, full_heal=True)
        routing = probe_postfix_recipient_routing(domain='gmail.com')
        report = check_outbound_smtp(include_django_probe=False)
    except Exception as exc:
        return {
            'success': False,
            'ok': False,
            'message': f'Tanılama hatası: {exc}',
            'fix_steps': ['Docker soketi veya Postfix konteyneri erişilemiyor olabilir.'],
        }

    fix_steps: list[str] = []
    routing_ok = bool(routing.get('ok'))
    if not routing_ok:
        fix_steps.extend(routing.get('fix_steps') or [])
        fix_steps.insert(0, routing.get('message') or 'Gmail yerel domain gibi yapılandırılmış (Dovecot hatası).')

    if report.get('mode') == 'relay':
        fix_steps.append(f'SMTP relay aktif: {report.get("relayhost")}')
        fix_steps.append('Dış posta relay üzerinden gidiyor; port 25 zorunlu değil.')
    elif report.get('ok'):
        fix_steps.append('Port 25 çıkışı çalışıyor — doğrudan internet SMTP kullanılabilir.')
        if routing_ok:
            fix_steps.append('Gmail routing OK — bounce devam ederse SPF, DKIM, DMARC ve PTR kontrol edin.')
        else:
            fix_steps.append('Port 25 açık olsa bile Postfix haritası hatalıysa mail Dovecot\'a gider (550).')
    else:
        fix_steps.append('Port 25 dışa kapalı (VPS sağlayıcısı engelliyor olabilir).')
        fix_steps.append('Kalıcı çözüm: .env → SMTP_RELAYHOST veya SMTP_RELAY_HOST/PORT/USER/PASSWORD')

    overall_ok = (bool(report.get('ok')) or report.get('mode') == 'relay') and routing_ok

    return {
        'success': True,
        'ok': overall_ok,
        'mode': report.get('mode') or 'direct',
        'relayhost': report.get('relayhost') or '',
        'message': (
            (routing.get('message') + ' ' if routing.get('message') and not routing_ok else '')
            + (report.get('message') or '')
        ).strip(),
        'probes': report.get('probes') or [],
        'routing': routing,
        'fix_steps': fix_steps,
        'recommendation': report.get('recommendation') or '',
    }


@router.get('/quota', summary='Depolama kotası')
def mail_quota(request: HttpRequest, outbound: bool = False):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    if outbound:
        return _outbound_delivery_report()

    used = account.current_storage_bytes
    quota = account.quota_bytes
    if quota > 0:
        percent = min(100.0, round((used / quota) * 100, 1))
    else:
        percent = 0.0
    return {
        'success': True,
        'used_bytes': used,
        'quota_bytes': quota,
        'percent': percent,
        'unlimited': quota == 0,
    }


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


@router.post('/sync-all', summary='Tüm ana klasörleri IMAP ile senkronize et')
def sync_all(request: HttpRequest):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}

    try:
        batch = sync_standard_folders(account, password, limit=200)
    except Exception as exc:
        return {'success': False, 'message': str(exc)}

    results = batch.get('synced', [])
    errors = batch.get('errors', [])
    if not results and errors:
        return {'success': False, 'message': errors[0]['error'], 'errors': errors}

    purged = 0
    try:
        purged = purge_blocked_inbound_cache(account)
    except Exception:
        pass

    _maybe_queue_agent_after_sync(account, password)

    return {
        'success': True,
        'synced': results,
        'errors': errors,
        'total_fetched': sum(r.get('fetched', 0) for r in results),
        'purged_blocked': purged,
    }


def _maybe_queue_agent_after_sync(account, password: str) -> None:
    if not password or not account.ai_available:
        return
    try:
        from webmail.ai.agent import get_or_create_agent_profile
        from webmail.models import MailAgentProfile
        from jir_core.session_secrets import encrypt_secret
        from webmail.tasks import ai_agent_cycle_task

        profile = get_or_create_agent_profile(account)
        if profile.mode == MailAgentProfile.MODE_OFF:
            return
        if not profile.auto_triage and not profile.auto_organize:
            return
        ai_agent_cycle_task.delay(
            account.id,
            encrypt_secret(password),
            triage=profile.auto_triage,
            organize=profile.auto_organize,
            digest=False,
        )
    except Exception:
        pass


class AiChatSchema(Schema):
    message: str
    context_subject: str = ''
    context_from: str = ''
    context_body: str = ''
    inbox_summary: str = ''
    selected_uid: int = 0
    selected_folder: str = 'INBOX'
    chat_history: list[dict] = []


class AiExecuteSchema(Schema):
    intent: str = 'chat'
    to: str = ''
    subject: str = ''
    body: str = ''
    send_at: str = ''
    uid: int = 0
    folder: str = 'INBOX'
    move_to: str = ''
    action_target: str = ''
    match_from: str = ''
    match_subject: str = ''
    rule_name: str = ''
    action_type: str = ''
    name: str = ''
    limit: int = 50
    summary: str = ''
    create_folder: bool = False


class AiTaskCreateSchema(Schema):
    instruction: str
    task_type: str = 'custom'
    context_subject: str = ''
    context_from: str = ''
    context_body: str = ''


class AgentProfileSchema(Schema):
    mode: Optional[str] = None
    auto_triage: Optional[bool] = None
    auto_organize: Optional[bool] = None
    auto_reply_suggest: Optional[bool] = None
    digest_enabled: Optional[bool] = None
    digest_frequency: Optional[str] = None
    digest_hour: Optional[int] = None
    triage_batch_size: Optional[int] = None
    organize_batch_size: Optional[int] = None


class AiRuleSchema(Schema):
    name: str
    enabled: bool = True
    priority: int = 100
    match_from: str = ''
    match_subject: str = ''
    match_category: str = ''
    action_type: str = 'archive'
    action_target: str = ''


class AiRulePatchSchema(Schema):
    name: Optional[str] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    match_from: Optional[str] = None
    match_subject: Optional[str] = None
    match_category: Optional[str] = None
    action_type: Optional[str] = None
    action_target: Optional[str] = None


class AgentRunSchema(Schema):
    triage: bool = True
    organize: bool = True
    digest: bool = False


class ReplyDraftSchema(Schema):
    folder: str = 'INBOX'
    uid: int
    tone: str = 'professional'
    instruction: str = ''
    context_subject: str = ''
    context_from: str = ''
    context_body: str = ''


class ReplySendSchema(Schema):
    to: str
    subject: str
    body_text: str
    body_html: str = ''
    uid: int = 0
    folder: str = 'INBOX'


class VipSenderSchema(Schema):
    pattern: str
    label: str = ''


class AiSettingsSchema(Schema):
    ai_enabled: Optional[bool] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_system_prompt: Optional[str] = None


class ScheduleMailSchema(Schema):
    to: str
    subject: str
    body_text: str = ''
    send_at: str
    cc: str = ''
    bcc: str = ''


AI_PROVIDERS = [
    {'id': 'openrouter', 'label': 'OpenRouter', 'default_model': 'openai/gpt-4o-mini'},
    {'id': 'openai', 'label': 'OpenAI', 'default_model': 'gpt-4o-mini'},
]


class WebmailSettingsPatchSchema(Schema):
    ai_enabled: Optional[bool] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_api_key: Optional[str] = None
    ai_system_prompt: Optional[str] = None


@router.get('/diagnostics/outbound', summary='Dış gönderim tanılaması')
def diagnostics_outbound(request: HttpRequest):
    """Port 25 / relay kontrolü (alternatif: GET /api/mail/quota?outbound=1)."""
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    return _outbound_delivery_report()


@router.get('/client-setup', summary='İstemci kurulum rehberi (IMAP/SMTP)')
def get_client_setup(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.client_setup import build_client_setup

    return {
        'success': True,
        'email': account.email,
        'client_setup': build_client_setup(account_email=account.email),
    }


@router.get('/settings', summary='Webmail ayarları')
def get_settings(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    account = MailAccount.objects.select_related('domain').filter(pk=account.pk).first()
    key = (account.ai_api_key or '').strip()
    from webmail.client_setup import build_client_setup

    return {
        'success': True,
        'email': account.email,
        'ai_enabled': bool(account.ai_enabled),
        'ai_provider': account.ai_provider or account.domain.ai_provider or 'openrouter',
        'ai_model': account.ai_model or account.domain.ai_default_model or 'openai/gpt-4o-mini',
        'ai_system_prompt': account.ai_system_prompt or account.domain.ai_system_prompt_default or '',
        'has_api_key': bool(key),
        'api_key_hint': ('••••' + key[-4:]) if len(key) >= 4 else '',
        'ai_available': bool(account.ai_available),
        'domain_ai_enabled': bool(account.domain.ai_enabled),
        'providers': AI_PROVIDERS,
        'client_setup': build_client_setup(account_email=account.email),
    }


@router.patch('/settings', summary='Webmail ayarlarını güncelle')
def patch_settings(request: HttpRequest, data: WebmailSettingsPatchSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    fields = []
    payload = data.dict(exclude_unset=True)
    if 'ai_api_key' in payload:
        key = (payload.pop('ai_api_key') or '').strip()
        account.ai_api_key = key
        fields.append('ai_api_key')
    for attr, val in payload.items():
        if val is not None:
            setattr(account, attr, val)
            fields.append(attr)
    if fields:
        account.save(update_fields=fields)
    return get_settings(request)


@router.get('/ai/status', summary='AI kullanılabilirlik')
def ai_status(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    account = MailAccount.objects.select_related('domain').filter(pk=account.pk).first()
    return {
        'success': True,
        'domain_ai_enabled': bool(account.domain.ai_enabled),
        'account_ai_enabled': bool(account.ai_enabled),
        'ai_available': bool(account.ai_available),
        'has_api_key': bool((account.ai_api_key or '').strip()),
        'model': account.ai_model or account.domain.ai_default_model,
    }


@router.post('/ai/chat', summary='AI sohbet / komut')
def ai_chat(request: HttpRequest, data: AiChatSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.service import ai_chat as run_chat

    return run_chat(
        account,
        data.message,
        context={
            'selected_subject': data.context_subject,
            'selected_from': data.context_from,
            'selected_body': data.context_body,
            'inbox_summary': data.inbox_summary,
            'selected_uid': data.selected_uid,
            'selected_folder': data.selected_folder or 'INBOX',
        },
        password=password or '',
        chat_history=data.chat_history or [],
    )


@router.post('/ai/compose', summary='AI ile metin üret')
def ai_compose(request: HttpRequest, data: AiChatSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.service import ai_compose_assist

    return ai_compose_assist(account, instruction=data.message)


@router.patch('/ai/settings', summary='Hesap AI ayarları')
def ai_settings_patch(request: HttpRequest, data: AiSettingsSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    fields = []
    for attr, val in data.dict(exclude_unset=True).items():
        if val is not None:
            setattr(account, attr, val)
            fields.append(attr)
    if fields:
        account.save(update_fields=fields)
    return {'success': True, 'ai_available': account.ai_available}


@router.get('/scheduled', summary='Planlanmış gönderimler')
def list_scheduled(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import ScheduledMail

    rows = ScheduledMail.objects.filter(
        account=account,
        status=ScheduledMail.STATUS_PENDING,
    ).order_by('send_at')[:50]
    return {
        'success': True,
        'items': [
            {
                'id': r.id,
                'to': r.to_addr,
                'subject': r.subject,
                'send_at': r.send_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.post('/schedule', summary='Planlı gönderim oluştur')
def schedule_mail(request: HttpRequest, data: ScheduleMailSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturumda parola yok — yeniden giriş yapın.'}

    from datetime import datetime
    from webmail.models import ScheduledMail

    try:
        send_at = datetime.fromisoformat(data.send_at.replace('Z', '+00:00'))
    except ValueError:
        return {'success': False, 'message': 'Geçersiz tarih formatı (ISO 8601 kullanın).'}

    row = ScheduledMail.objects.create(
        account=account,
        to_addr=data.to,
        cc_addr=data.cc or '',
        bcc_addr=data.bcc or '',
        subject=data.subject,
        body_text=data.body_text,
        send_at=send_at,
    )
    return {'success': True, 'id': row.id, 'send_at': row.send_at.isoformat()}


@router.post('/send-attachments', summary='Ek dosyalı gönderim')
def send_with_attachments(request: HttpRequest):
    import logging
    log = logging.getLogger(__name__)
    try:
        account, password = _get_account_and_password(request)
        if not account:
            return {'success': False, 'message': 'Oturum yok'}
        if not password:
            return {'success': False, 'message': 'Oturumda parola yok — yeniden giriş yapın.'}

        from webmail.send_validation import validate_outbound_recipients

        to_raw = request.POST.get('to', '')
        subject = request.POST.get('subject', '')
        body_text = request.POST.get('body_text', '')
        body_html = request.POST.get('body_html', '')
        cc_raw = request.POST.get('cc', '')
        bcc_raw = request.POST.get('bcc', '')

        check = validate_outbound_recipients(account, to_raw, cc_raw, bcc_raw)
        if not check['ok']:
            return {'success': False, 'message': check['message']}

        try:
            from management.outbound_autoconfig import ensure_outbound_delivery

            ensure_outbound_delivery(fix=True, full_heal=False)
        except Exception as exc:
            log.debug('ensure_outbound_delivery: %s', exc)

        background = request.POST.get('background', 'true').lower() not in ('0', 'false', 'no')
        to_list = parse_recipient_list(to_raw)
        cc_list = parse_recipient_list(cc_raw) or None
        bcc_list = parse_recipient_list(bcc_raw) or None

        if background:
            from jir_core.session_secrets import encrypt_secret
            from webmail.outbound_queue import queue_outbound_send, save_outbound_attachments
            from webmail.tasks import send_mail_async

            snippet = (body_text or body_html or '')[:480]
            log_row = MailOutboundLog.objects.create(
                account=account,
                to_addr=', '.join(to_list),
                subject=subject,
                snippet=snippet,
                status=MailOutboundLog.STATUS_PENDING,
            )
            files = list(request.FILES.getlist('attachments'))
            meta = save_outbound_attachments(log_row.id, files) if files else []
            try:
                send_mail_async.delay(
                    outbound_id=log_row.id,
                    password_enc=encrypt_secret(password),
                    to=to_list,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                    cc=cc_list,
                    bcc=bcc_list,
                    attachments_meta=meta,
                )
                out = {
                    'success': True,
                    'queued': True,
                    'outbound_id': log_row.id,
                    'message': 'Mesaj arka planda gönderiliyor.',
                }
            except Exception as exc:
                log.warning('Celery kuyruk hatası (ekli): %s', exc)
                from webmail.tasks import send_mail_async as send_async_fn

                out = send_async_fn(
                    outbound_id=log_row.id,
                    password_enc=encrypt_secret(password),
                    to=to_list,
                    subject=subject,
                    body_text=body_text,
                    body_html=body_html,
                    cc=cc_list,
                    bcc=bcc_list,
                    attachments_meta=meta,
                )
                out['queued'] = False
            for w in check.get('warnings') or []:
                out.setdefault('warnings', []).append(w)
            return out

        attachments = []
        for f in request.FILES.getlist('attachments'):
            attachments.append({
                'filename': f.name,
                'mime_type': f.content_type or 'application/octet-stream',
                'content': f.read(),
            })

        result = send_mail(
            account, password,
            to=to_list,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            attachments=attachments or None,
        )
        if result.get('success'):
            for w in check.get('warnings') or []:
                result.setdefault('warnings', []).append(w)
        return _sanitize_send_result(result)
    except Exception as exc:
        log.exception('POST /api/mail/send-attachments')
        return {'success': False, 'message': f'Gönderim hatası: {exc}'}


@router.get('/outbound/pending', summary='Bekleyen gönderimler')
def outbound_pending(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    rows = MailOutboundLog.objects.filter(
        account=account,
        status=MailOutboundLog.STATUS_PENDING,
    ).order_by('-created_at')[:20]
    return {
        'success': True,
        'items': [
            {
                'id': r.id,
                'to': r.to_addr,
                'subject': r.subject,
                'created_at': r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@router.get('/outbound/{outbound_id}', summary='Gönderim durumu')
def outbound_status(request: HttpRequest, outbound_id: int):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    row = MailOutboundLog.objects.filter(account=account, pk=outbound_id).first()
    if not row:
        return {'success': False, 'message': 'Kayıt bulunamadı'}
    return {
        'success': True,
        'id': row.id,
        'status': row.status,
        'error_message': row.error_message,
        'message_id': row.message_id,
    }


@router.post('/ai/analyze', summary='Seçili maili AI ile analiz et')
def ai_analyze(request: HttpRequest, data: AiChatSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.service import ai_analyze_message

    return ai_analyze_message(
        account,
        subject=data.context_subject,
        from_addr=data.context_from,
        body_text=data.context_body or data.message,
    )


@router.post('/ai/execute', summary='AI aksiyonunu uygula (gönder/planla)')
def ai_execute(request: HttpRequest, data: AiExecuteSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.service import execute_ai_action

    return execute_ai_action(account, password, data.dict())


@router.post('/ai/tasks', summary='Arka plan AI görevi oluştur')
def ai_create_task(request: HttpRequest, data: AiTaskCreateSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from jir_core.session_secrets import encrypt_secret
    from webmail.ai.service import create_ai_task
    from webmail.models import MailAiTask
    from webmail.tasks import run_ai_task

    ctx = {
        'subject': data.context_subject,
        'from': data.context_from,
        'body': data.context_body,
    }
    task = create_ai_task(
        account,
        data.instruction,
        task_type=data.task_type or MailAiTask.TYPE_CUSTOM,
        context=ctx,
    )
    pwd_enc = encrypt_secret(password) if password else ''
    try:
        run_ai_task.delay(task.id, pwd_enc)
    except Exception:
        run_ai_task(task.id, pwd_enc)
    return {'success': True, 'task_id': task.id, 'status': task.status}


@router.get('/ai/tasks', summary='AI görev listesi')
def ai_list_tasks(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailAiTask

    rows = MailAiTask.objects.filter(account=account).order_by('-created_at')[:30]
    return {
        'success': True,
        'items': [
            {
                'id': t.id,
                'instruction': t.instruction[:200],
                'task_type': t.task_type,
                'status': t.status,
                'created_at': t.created_at.isoformat(),
                'finished_at': t.finished_at.isoformat() if t.finished_at else None,
                'result_preview': (t.result.get('reply') or t.result.get('message') or '')[:300]
                if isinstance(t.result, dict) else '',
            }
            for t in rows
        ],
    }


def _agent_profile_dict(profile) -> dict:
    return {
        'mode': profile.mode,
        'auto_triage': profile.auto_triage,
        'auto_organize': profile.auto_organize,
        'auto_reply_suggest': profile.auto_reply_suggest,
        'digest_enabled': profile.digest_enabled,
        'digest_frequency': profile.digest_frequency,
        'digest_hour': profile.digest_hour,
        'triage_batch_size': profile.triage_batch_size,
        'organize_batch_size': profile.organize_batch_size,
        'last_triage_at': profile.last_triage_at.isoformat() if profile.last_triage_at else None,
        'last_organize_at': profile.last_organize_at.isoformat() if profile.last_organize_at else None,
        'last_digest_at': profile.last_digest_at.isoformat() if profile.last_digest_at else None,
        'last_digest_preview': (profile.last_digest_text or '')[:400],
    }


@router.get('/ai/agent/profile', summary='AI ajan profili')
def agent_profile_get(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.agent import get_or_create_agent_profile

    profile = get_or_create_agent_profile(account)
    return {'success': True, 'profile': _agent_profile_dict(profile)}


@router.patch('/ai/agent/profile', summary='AI ajan profili güncelle')
def agent_profile_patch(request: HttpRequest, data: AgentProfileSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.agent import get_or_create_agent_profile

    profile = get_or_create_agent_profile(account)
    fields = []
    for attr, val in data.dict(exclude_unset=True).items():
        if val is not None:
            setattr(profile, attr, val)
            fields.append(attr)
    if fields:
        profile.save(update_fields=fields + ['updated_at'])
    return {'success': True, 'profile': _agent_profile_dict(profile)}


@router.post('/ai/agent/run', summary='Tam ajan döngüsü (triage + organize)')
def agent_run(request: HttpRequest, data: AgentRunSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok.'}
    from jir_core.session_secrets import encrypt_secret
    from webmail.tasks import ai_agent_cycle_task

    try:
        ai_agent_cycle_task.delay(
            account.id,
            encrypt_secret(password),
            triage=data.triage,
            organize=data.organize,
            digest=data.digest,
        )
        return {'success': True, 'queued': True, 'message': 'AI ajan arka planda çalışıyor.'}
    except Exception:
        from webmail.ai.agent import run_agent_cycle

        result = run_agent_cycle(
            account,
            password,
            triage=data.triage,
            organize=data.organize,
            digest=data.digest,
        )
        return result


@router.post('/ai/triage/inbox', summary='Gelen kutusunu AI ile sınıflandır')
def triage_inbox(request: HttpRequest, limit: int = 20):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok.'}
    from webmail.ai.agent import batch_triage_inbox

    return batch_triage_inbox(account, password, limit=min(limit, 50))


@router.post('/ai/organize/inbox', summary='Gelen kutusunu organize et')
def organize_inbox_api(request: HttpRequest, autopilot: bool = False):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok.'}
    from webmail.ai.agent import organize_inbox

    return organize_inbox(account, password, autopilot=autopilot)


@router.get('/ai/digest', summary='Gelen kutusu brifingi')
def get_digest(request: HttpRequest, refresh: bool = False):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.agent import generate_inbox_digest, get_or_create_agent_profile

    profile = get_or_create_agent_profile(account)
    if not refresh and profile.last_digest_text:
        return {
            'success': True,
            'digest': profile.last_digest_text,
            'generated_at': profile.last_digest_at.isoformat() if profile.last_digest_at else None,
            'cached': True,
        }
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok.'}
    return generate_inbox_digest(account, password)


@router.get('/ai/rules', summary='Posta kuralları')
def list_ai_rules(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailAiRule

    rows = MailAiRule.objects.filter(account=account).order_by('priority', 'id')
    return {
        'success': True,
        'items': [
            {
                'id': r.id,
                'name': r.name,
                'enabled': r.enabled,
                'priority': r.priority,
                'match_from': r.match_from,
                'match_subject': r.match_subject,
                'match_category': r.match_category,
                'action_type': r.action_type,
                'action_target': r.action_target,
                'created_by_ai': r.created_by_ai,
            }
            for r in rows
        ],
    }


@router.post('/ai/rules', summary='Posta kuralı ekle')
def create_ai_rule(request: HttpRequest, data: AiRuleSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailAiRule

    row = MailAiRule.objects.create(account=account, **data.dict())
    return {'success': True, 'id': row.id}


@router.patch('/ai/rules/{rule_id}', summary='Kural güncelle')
def patch_ai_rule(request: HttpRequest, rule_id: int, data: AiRulePatchSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailAiRule

    row = MailAiRule.objects.filter(account=account, pk=rule_id).first()
    if not row:
        return {'success': False, 'message': 'Kural bulunamadı'}
    for attr, val in data.dict(exclude_unset=True).items():
        if val is not None:
            setattr(row, attr, val)
    row.save()
    return {'success': True}


@router.delete('/ai/rules/{rule_id}', summary='Kural sil')
def delete_ai_rule(request: HttpRequest, rule_id: int):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailAiRule

    n, _ = MailAiRule.objects.filter(account=account, pk=rule_id).delete()
    return {'success': n > 0}


@router.get('/ai/reply/pending', summary='Yanıt bekleyen mailler')
def reply_pending_list(request: HttpRequest, limit: int = 20):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.reply import list_needs_reply

    return list_needs_reply(account, limit=min(limit, 50))


@router.post('/ai/reply/draft', summary='AI yanıt taslağı üret')
def reply_draft(request: HttpRequest, data: ReplyDraftSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.reply import generate_reply_draft
    from webmail.models import MailFolder, MailMessageCache

    out = generate_reply_draft(
        account,
        password,
        folder=data.folder,
        uid=data.uid,
        tone=data.tone,
        instruction=data.instruction,
        cached_subject=data.context_subject,
        cached_from=data.context_from,
        cached_body=data.context_body,
    )
    if out.get('success') and data.uid > 0:
        folder_obj = MailFolder.objects.filter(account=account, name__iexact=data.folder).first()
        if folder_obj:
            row = MailMessageCache.objects.filter(folder=folder_obj, uid=data.uid).first()
            if row:
                ai = dict(row.ai_meta or {})
                ai['reply_draft'] = out.get('body') or ''
                ai['needs_reply'] = True
                row.ai_meta = ai
                row.save(update_fields=['ai_meta'])
    return out


@router.post('/ai/reply/send', summary='AI yanıtını arka planda gönder')
def reply_send(request: HttpRequest, data: ReplySendSchema):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.reply import send_reply_draft

    return send_reply_draft(
        account,
        password,
        to=data.to,
        subject=data.subject,
        body_text=data.body_text,
        body_html=data.body_html,
    )


@router.get('/ai/agent/stats', summary='AI ajan istatistikleri')
def agent_stats_api(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.approval import agent_stats

    return agent_stats(account)


@router.get('/ai/approvals', summary='Onay bekleyen aksiyonlar')
def list_approvals(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.approval import list_pending_actions

    return list_pending_actions(account)


@router.post('/ai/approvals/{action_id}/approve', summary='Aksiyonu onayla ve uygula')
def approve_pending(request: HttpRequest, action_id: int):
    account, password = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.approval import approve_action

    return approve_action(account, password, action_id)


@router.post('/ai/approvals/{action_id}/reject', summary='Aksiyonu reddet')
def reject_pending(request: HttpRequest, action_id: int):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.ai.approval import reject_action

    return reject_action(account, action_id)


@router.get('/ai/vip', summary='VIP gönderen listesi')
def list_vip(request: HttpRequest):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailVipSender

    rows = MailVipSender.objects.filter(account=account, enabled=True).order_by('pattern')
    return {
        'success': True,
        'items': [{'id': r.id, 'pattern': r.pattern, 'label': r.label} for r in rows],
    }


@router.post('/ai/vip', summary='VIP gönderen ekle')
def add_vip(request: HttpRequest, data: VipSenderSchema):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailVipSender

    pat = (data.pattern or '').strip().lower()
    if not pat:
        return {'success': False, 'message': 'Desen gerekli'}
    row, created = MailVipSender.objects.get_or_create(
        account=account,
        pattern=pat,
        defaults={'label': data.label or ''},
    )
    return {'success': True, 'id': row.id, 'created': created}


@router.delete('/ai/vip/{vip_id}', summary='VIP gönderen sil')
def delete_vip(request: HttpRequest, vip_id: int):
    account, _ = _get_account_and_password(request)
    if not account:
        return {'success': False, 'message': 'Oturum yok'}
    from webmail.models import MailVipSender

    n, _ = MailVipSender.objects.filter(account=account, pk=vip_id).delete()
    return {'success': n > 0}


def mail_stream(request: HttpRequest):
    """SSE endpoint — yeni mail push."""
    account_id = request.session.get('account_id')
    if not account_id:
        from django.http import JsonResponse
        return JsonResponse({'success': False, 'message': 'Oturum yok'}, status=403)
    return webmail_sse_response(int(account_id))
