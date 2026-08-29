"""IMAPClient wrapper'ı.

Dovecot IMAP sunucusuna kullanıcı adıyla bağlanır. Sistem, kullanıcının
düz şifresini saklamadığı için (`password_hash` bcrypt) login sırasında
session'a şifreyi cache'leyip IMAP bağlantısı için kullanır.
"""
from __future__ import annotations

import email
import logging
import re
import ssl
from contextlib import contextmanager
from datetime import datetime
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime
from typing import Iterator

from django.conf import settings

from management.mail_service_endpoint import resolve_mail_endpoint
from management.mail_tls import imap_ssl_verify_required, imap_tls_context

logger = logging.getLogger(__name__)


def _decode_header(value: str) -> str:
    if not value:
        return ''
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _format_addresses(value: str) -> tuple[str, str]:
    name, addr = parseaddr(value or '')
    return _decode_header(name), addr


@contextmanager
def imap_connection(account, password: str) -> Iterator:
    """Verilen MailAccount için IMAP bağlantısı açar (context manager).

    Bağlantı her zaman SSL üzerinden (port 993). Bağlantı sonunda otomatik
    kapanır.
    """
    from imapclient import IMAPClient

    host, port = resolve_mail_endpoint('dovecot', int(getattr(settings, 'IMAP_PORT', 993)))
    ssl_required = getattr(settings, 'IMAP_SSL', True)
    if not ssl_required:
        raise ValueError('IMAP düz metin devre dışı (MAIL_TLS_MODE=e2e).')

    ssl_context = imap_tls_context()
    if imap_ssl_verify_required() and ssl_context is None:
        raise ssl.SSLError('IMAP TLS doğrulaması için SSL bağlamı oluşturulamadı.')

    client = IMAPClient(
        host=host,
        port=port,
        ssl=True,
        ssl_context=ssl_context,
        use_uid=True,
        timeout=30,
    )
    try:
        client.login(account.email, password)
        yield client
    finally:
        try:
            client.logout()
        except Exception:
            pass


def _parse_envelope_to_meta(envelope, raw_size: int, flags: list) -> dict:
    """IMAP envelope'unu DB cache modeli için sözlüğe çevirir."""
    subject = ''
    if envelope.subject:
        try:
            subject = _decode_header(envelope.subject.decode('utf-8', 'replace'))
        except Exception:
            subject = str(envelope.subject)

    from_name, from_addr = '', ''
    if envelope.from_:
        addr = envelope.from_[0]
        from_addr = f'{addr.mailbox.decode()}@{addr.host.decode()}' if addr.mailbox and addr.host else ''
        if addr.name:
            try:
                from_name = _decode_header(addr.name.decode('utf-8', 'replace'))
            except Exception:
                from_name = str(addr.name)

    to_parts = []
    if envelope.to:
        for a in envelope.to:
            if a.mailbox and a.host:
                to_parts.append(f'{a.mailbox.decode()}@{a.host.decode()}')

    date_obj = None
    try:
        if envelope.date:
            date_obj = envelope.date if isinstance(envelope.date, datetime) else parsedate_to_datetime(envelope.date)
    except Exception:
        date_obj = None

    flag_set = set()
    for f in (flags or []):
        try:
            flag_set.add(f.decode() if isinstance(f, bytes) else str(f))
        except Exception:
            pass

    return {
        'subject': subject[:998],
        'from_addr': from_addr[:500],
        'from_name': from_name[:255],
        'to_addr': ', '.join(to_parts)[:2000],
        'date': date_obj,
        'flags': list(flag_set),
        'is_seen': '\\Seen' in flag_set,
        'is_flagged': '\\Flagged' in flag_set,
        'is_answered': '\\Answered' in flag_set,
        'is_draft': '\\Draft' in flag_set,
        'raw_size': raw_size or 0,
    }


# UI klasör adı → IMAP'ta olası isimler
FOLDER_ALIASES = {
    'inbox': ['INBOX'],
    'spam': ['Junk', 'Spam', 'Junk E-mail', 'INBOX.Junk', 'INBOX.Spam', '.Junk', '.Spam'],
    'junk': ['Junk', 'Spam', 'Junk E-mail', 'INBOX.Junk', 'INBOX.Spam', '.Junk', '.Spam'],
    'sent': ['Sent', 'Sent Messages', 'INBOX.Sent', '.Sent'],
    'drafts': ['Drafts', 'INBOX.Drafts', '.Drafts'],
    'trash': ['Trash', 'INBOX.Trash', '.Trash', 'Deleted Messages'],
    'archive': ['Archive', 'INBOX.Archive', '.Archive', 'Archives'],
}


def is_spam_folder_name(folder_name: str) -> bool:
    """IMAP klasör adı spam/junk mı?"""
    raw = (folder_name or '').strip().lower()
    if not raw:
        return False
    tail = raw.split('/')[-1].replace('.', '')
    return tail in ('junk', 'spam', 'junk e-mail', 'junk email') or 'junk' in tail or tail.endswith('spam')


def list_imap_folder_names(account, password: str) -> list[str]:
    with imap_connection(account, password) as client:
        return [entry[2] for entry in client.list_folders()]


def resolve_imap_folder(account, password: str, folder: str) -> str:
    """Webmail klasör adını sunucudaki gerçek IMAP klasörüne eşle."""
    wanted = (folder or 'INBOX').strip()
    try:
        available = list_imap_folder_names(account, password)
    except Exception:
        return wanted

    if wanted in available:
        return wanted

    key = wanted.lower().split('/')[-1].replace('.', '')
    for candidate in FOLDER_ALIASES.get(key, [wanted]):
        if candidate in available:
            return candidate
        for name in available:
            if name.lower() == candidate.lower() or name.lower().endswith('/' + candidate.lower()):
                return name
    return wanted


def sync_folder_metadata(account, password: str, folder_name: str = 'INBOX', *, limit: int = 200) -> dict:
    """Folder içindeki son N mesajın metadata'sını DB cache'e alır."""
    from .models import MailFolder, MailMessageCache

    with imap_connection(account, password) as client:
        select_info = client.select_folder(folder_name)
        uidvalidity = select_info.get(b'UIDVALIDITY') or 0
        total = select_info.get(b'EXISTS') or 0

        folder_obj, _ = MailFolder.objects.update_or_create(
            account=account, name=folder_name,
            defaults={
                'display_name': folder_name,
                'uidvalidity': uidvalidity,
                'total': total,
                'last_synced': datetime.utcnow(),
            },
        )

        uids = client.search(['ALL'])
        if not uids:
            return {'folder': folder_name, 'fetched': 0}

        recent_uids = uids[-limit:]
        fetch_data = client.fetch(
            recent_uids,
            [
                'ENVELOPE',
                'FLAGS',
                'RFC822.SIZE',
                'BODYSTRUCTURE',
                'BODY.PEEK[HEADER.FIELDS (FROM SENDER REPLY-TO RETURN-PATH SUBJECT MESSAGE-ID AUTHENTICATION-RESULTS RECEIVED-SPF)]',
            ],
        )

        from .sender import (
            build_sender_info,
            sender_info_from_imap_headers,
            should_block_inbound,
        )

        is_inbound = folder_name.upper() == 'INBOX' or is_spam_folder_name(folder_name)
        account_email = account.email

        fetched = 0
        unread_count = 0
        for uid, data in fetch_data.items():
            envelope = data.get(b'ENVELOPE')
            flags = data.get(b'FLAGS', [])
            size = data.get(b'RFC822.SIZE', 0)
            if not envelope:
                continue

            meta = _parse_envelope_to_meta(envelope, size, list(flags))
            header_raw = None
            for key, val in data.items():
                if isinstance(key, bytes) and b'HEADER.FIELDS' in key:
                    header_raw = val
                    break
            if header_raw:
                sender = sender_info_from_imap_headers(
                    header_raw, account_email, is_inbound=is_inbound,
                )
            else:
                sender = build_sender_info(
                    from_raw=meta.get('from_name', '') + (
                        f' <{meta["from_addr"]}>' if meta.get('from_addr') else ''
                    ),
                    account_email=account_email,
                    is_inbound=is_inbound,
                    subject=meta.get('subject', ''),
                )
            if sender.get('from_email'):
                meta['from_addr'] = sender['from_email'][:500]
                meta['from_name'] = (sender.get('from_name') or '')[:255]
            meta['sender_meta'] = sender

            if is_inbound and should_block_inbound(sender):
                MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_deleted=True)
                continue

            meta['is_deleted'] = False

            if not meta['is_seen']:
                unread_count += 1

            try:
                MailMessageCache.objects.update_or_create(
                    folder=folder_obj, uid=uid,
                    defaults=meta,
                )
            except Exception as exc:
                if 'sender_meta' in str(exc):
                    meta.pop('sender_meta', None)
                    MailMessageCache.objects.update_or_create(
                        folder=folder_obj, uid=uid,
                        defaults=meta,
                    )
                else:
                    raise
            fetched += 1

        folder_obj.unread = unread_count
        folder_obj.save(update_fields=['unread'])

    return {'folder': folder_name, 'fetched': fetched, 'unread': unread_count}


def sync_standard_folders(account, password: str, *, limit: int = 200) -> dict:
    """INBOX + Sent + Drafts + Trash — sunucudaki gerçek klasör adlarıyla."""
    seen = set()
    results = []
    errors = []
    for ui_key in ('inbox', 'spam', 'sent', 'drafts', 'trash', 'archive'):
        try:
            seed = FOLDER_ALIASES[ui_key][0]
            imap_name = resolve_imap_folder(account, password, seed)
            if imap_name in seen:
                continue
            seen.add(imap_name)
            results.append(sync_folder_metadata(account, password, imap_name, limit=limit))
        except Exception as exc:
            errors.append({'folder': ui_key, 'error': str(exc)})
    return {'synced': results, 'errors': errors}


def fetch_message_body(account, password: str, folder_name: str, uid: int) -> dict:
    """Bir mesajın HTML ve plain body'sini IMAP'tan getirir."""
    with imap_connection(account, password) as client:
        client.select_folder(folder_name)
        data = client.fetch([uid], ['RFC822'])
        raw = data.get(uid, {}).get(b'RFC822')
        if not raw:
            return {'html': '', 'plain': '', 'attachments': []}

        msg = email.message_from_bytes(raw)

        html_body = ''
        plain_body = ''
        attachments: list[dict] = []

        for part in msg.walk():
            ctype = part.get_content_type()
            disposition = (part.get('Content-Disposition') or '').lower()

            if 'attachment' in disposition or part.get_filename():
                filename = _decode_header(part.get_filename() or 'attachment')
                payload = part.get_payload(decode=True) or b''
                attachments.append({
                    'filename': filename,
                    'mime_type': ctype,
                    'size': len(payload),
                })
                continue

            if part.is_multipart():
                continue

            charset = part.get_content_charset() or 'utf-8'
            try:
                content = (part.get_payload(decode=True) or b'').decode(charset, errors='replace')
            except Exception:
                content = ''

            if ctype == 'text/html' and not html_body:
                html_body = content
            elif ctype == 'text/plain' and not plain_body:
                plain_body = content

        from .sender import sender_info_from_message

        is_inbound = folder_name.upper() == 'INBOX' or is_spam_folder_name(folder_name)
        sender = sender_info_from_message(msg, account.email, is_inbound=is_inbound)

        return {
            'html': html_body,
            'plain': plain_body,
            'attachments': attachments,
            'sender': sender,
        }


def set_flag(account, password: str, folder_name: str, uid: int, flag: str, *, add: bool = True) -> None:
    """\Seen, \Flagged gibi flag'leri ekle/kaldır."""
    with imap_connection(account, password) as client:
        client.select_folder(folder_name)
        if add:
            client.add_flags([uid], [flag])
        else:
            client.remove_flags([uid], [flag])


def move_message(account, password: str, folder_name: str, uid: int, target_folder: str) -> None:
    with imap_connection(account, password) as client:
        client.select_folder(folder_name)
        client.move([uid], target_folder)


def delete_message(account, password: str, folder_name: str, uid: int) -> None:
    with imap_connection(account, password) as client:
        client.select_folder(folder_name)
        client.delete_messages([uid])
        client.expunge()


_SENT_FOLDER_CANDIDATES = ('Sent', 'Sent Messages', 'INBOX.Sent', 'Sent Items')


def resolve_sent_folder_name(account, password: str) -> str:
    """Hesabın Sent klasör adını bul."""
    with imap_connection(account, password) as client:
        for _flags, _delimiter, name in client.list_folders():
            if name in _SENT_FOLDER_CANDIDATES:
                return name
            if isinstance(name, str) and name.lower() in ('sent', 'sent messages', 'sent items'):
                return name
    return 'Sent'


def append_message_to_sent(account, password: str, raw_message: bytes) -> str:
    """Gönderilen mesajı IMAP Sent klasörüne ekle; klasör adını döndür."""
    folder = resolve_sent_folder_name(account, password)
    with imap_connection(account, password) as client:
        client.append(folder, raw_message, [b'\\Seen'], None)
    return folder


def build_mime_draft(
    account,
    *,
    to: str = '',
    subject: str = '',
    body_text: str = '',
    body_html: str = '',
    cc: str = '',
) -> bytes:
    """Taslak için RFC822 ham mesaj."""
    from email.message import EmailMessage

    msg = EmailMessage()
    msg['From'] = account.email
    if to:
        msg['To'] = to
    if cc:
        msg['Cc'] = cc
    msg['Subject'] = subject or '(taslak)'
    if body_html:
        msg.set_content(body_text or '', subtype='plain', charset='utf-8')
        msg.add_alternative(body_html, subtype='html', charset='utf-8')
    else:
        msg.set_content(body_text or '', subtype='plain', charset='utf-8')
    return msg.as_bytes()


def append_message_to_drafts(account, password: str, raw_message: bytes) -> str:
    """Taslağı IMAP Drafts klasörüne ekle."""
    folder = resolve_imap_folder(account, password, 'Drafts')
    with imap_connection(account, password) as client:
        client.append(folder, raw_message, [b'\\Draft'], None)
    return folder


def remove_draft_message(account, password: str, uid: int) -> None:
    """Önceki taslak satırını sil (yeniden kayıt öncesi)."""
    folder = resolve_imap_folder(account, password, 'Drafts')
    delete_message(account, password, folder, uid)
