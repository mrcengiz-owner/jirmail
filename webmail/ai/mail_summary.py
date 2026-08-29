"""Tek mail özeti — konu/gönderen eşleştirme, IMAP içerik, AI özet."""
from __future__ import annotations

import re
from typing import Any

from webmail.ai.client import chat_completion, is_meaningful_ai_text, sanitize_ai_text

_SUMMARY_SYSTEM = (
    'Sen e-posta özet asistanısın. Yalnızca Türkçe, madde madde kısa özet yaz. '
    'Güvenlik etiketi veya moderasyon metni yazma. Konu, ana noktalar, '
    'varsa istenen aksiyon ve aciliyet belirt.'
)

_RE_SUBJECT_MAIL = re.compile(
    r'(?P<subject>.+?)\s+'
    r'(?:mail(?:ini|i|ını|ını|indeki|deki)?|e-?post(?:a(?:sını|yı|sı)?)?|ileti(?:yi|sini)?)\s+'
    r'(?:özetle|özetler\s+misin|özetler\s+mısın|özet\s+yap|özet\s+çıkar|özet\s+ver)',
    re.I,
)
_RE_MAIL_SUBJECT = re.compile(
    r'(?:mail(?:i|ini|indeki|deki)?|e-?post(?:a(?:yı|sı)?)?|ileti(?:yi|sini)?)\s+'
    r'[«"“\']?(?P<subject>.+?)[»"”\']?\s+'
    r'(?:özetle|özetler\s+misin|özetler\s+mısın|özet\s+yap|özet\s+çıkar|özet\s+ver)',
    re.I,
)
_FOLLOWUP_MARKERS = (
    'içeriğin özet',
    'içeriği özet',
    'mailin özet',
    'maili özet',
    'bunun özet',
    'özetini getir',
    'detaylı özet',
    'tam özet',
    'içerik özet',
    'mesajın özet',
)


def _is_followup_summary_request(message: str) -> bool:
    low = (message or '').lower()
    return any(m in low for m in _FOLLOWUP_MARKERS)
_RE_INBOX_DIGEST = re.compile(
    r'(?:'
    r'bugünkü\s+özeti|bugünkü\s+özet|günün\s+özeti|günlük\s+özet|'
    r'inbox\s+özeti|postalarımın\s+özeti|gelen\s+kutusu\s+özeti|'
    r'(?:tüm\s+)?mailleri?\s+özetle|(?:tüm\s+)?mail(?:leri|erini)?\s+özetle|postaları\s+özetle|'
    r'(?:gelen\s+kutusu|inbox)(?:\s+|\s*için\s+)özet|'
    r'(?:ne\s+var|neler\s+var)\s+(?:gelen\s+kutusu|inbox)|'
    r'brifing|digest'
    r')',
    re.I,
)


def extract_subject_query(message: str) -> str:
    text = (message or '').strip()
    if not text:
        return ''
    for pattern in (_RE_SUBJECT_MAIL, _RE_MAIL_SUBJECT):
        m = pattern.search(text)
        if m:
            subj = (m.group('subject') or '').strip().strip('"\'«»“”')
            subj = re.sub(r'\s+(mail|e-?posta|ileti)$', '', subj, flags=re.I).strip()
            if len(subj) >= 2:
                return subj
    return ''


def is_mail_summary_request(message: str) -> bool:
    text = (message or '').strip()
    if not text:
        return False
    if extract_subject_query(text):
        return True
    if _is_followup_summary_request(text):
        return True
    if re.search(r'(?:bu\s+mail|seçili\s+mail|bunu)\s+(?:özetle|analiz\s+et)', text, re.I):
        return True
    return False


def is_inbox_digest_request(message: str) -> bool:
    text = (message or '').strip()
    if not text:
        return False
    if is_mail_summary_request(text):
        return False
    if _RE_INBOX_DIGEST.search(text):
        return True
    if re.search(r'(?:özeti\s+ver|özet\s+ver|özet\s+çıkar|özet\s+yap)$', text, re.I):
        return True
    if re.search(r'^özetler\s+m[ıi]s[ıi]n\??$', text, re.I):
        return True
    return False


def resolve_summary_target(
    account,
    message: str,
    *,
    context: dict | None = None,
    chat_history: list[dict] | None = None,
) -> tuple[int, str, str] | None:
    """(uid, folder, subject) veya None."""
    from webmail.ai.nl_commands import find_messages_by_criteria

    ctx = context or {}
    hist = chat_history or []
    folder = ctx.get('selected_folder') or 'INBOX'

    def _find(subject: str) -> tuple[int, str, str] | None:
        subj = (subject or '').strip()
        if not subj:
            return None
        pairs = find_messages_by_criteria(
            account,
            folder=folder,
            match_subject=subj,
            limit=1,
        )
        if pairs:
            return pairs[0][0], pairs[0][1], subj
        rows = find_messages_by_criteria(account, folder=folder, limit=30)
        low = subj.lower()
        for uid, fld in rows:
            from webmail.models import MailFolder, MailMessageCache

            fo = MailFolder.objects.filter(account=account, name=fld).first()
            if not fo:
                continue
            row = MailMessageCache.objects.filter(folder=fo, uid=uid, is_deleted=False).first()
            if row and row.subject and low in row.subject.lower():
                return uid, fld, row.subject
        return None

    subj = extract_subject_query(message)
    if subj:
        hit = _find(subj)
        if hit:
            return hit

    uid = int(ctx.get('selected_uid') or 0)
    if uid and (
        _is_followup_summary_request(message)
        or re.search(r'(?:bu\s+mail|seçili\s+mail|bunu)\s+(?:özetle|analiz)', message or '', re.I)
    ):
        return uid, folder, ctx.get('selected_subject') or ctx.get('context_subject') or ''

    for turn in reversed(hist):
        if turn.get('role') != 'user':
            continue
        prev_subj = extract_subject_query(turn.get('text') or '')
        if prev_subj:
            hit = _find(prev_subj)
            if hit:
                return hit

    if uid and _is_followup_summary_request(message):
        return uid, folder, ctx.get('selected_subject') or ctx.get('context_subject') or ''

    if uid and extract_subject_query(message):
        return uid, folder, ctx.get('selected_subject') or ''

    return None


def _plain_from_body(body_data: dict) -> str:
    plain = (body_data.get('plain') or '').strip()
    if plain:
        return plain
    html = body_data.get('html') or ''
    if html:
        return re.sub(r'<[^>]+>', ' ', html)
    return ''


def summarize_message(
    account,
    password: str,
    *,
    uid: int,
    folder: str = 'INBOX',
    subject: str = '',
    from_addr: str = '',
) -> dict[str, Any]:
    from webmail.imap_client import fetch_message_body, resolve_imap_folder
    from webmail.models import MailFolder, MailMessageCache

    from webmail.ai.service import resolve_ai_config

    cfg = resolve_ai_config(account)
    if not cfg:
        return {'success': False, 'message': 'AI kullanılamıyor'}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok — yeniden giriş yapın.'}
    if not uid:
        return {'success': False, 'message': 'Özetlenecek mail bulunamadı.'}

    imap_folder = resolve_imap_folder(account, password, folder)
    subj = subject
    frm = from_addr
    body_text = ''

    folder_obj = MailFolder.objects.filter(account=account, name=imap_folder).first()
    if folder_obj:
        row = MailMessageCache.objects.filter(folder=folder_obj, uid=uid, is_deleted=False).first()
        if row:
            subj = subj or row.subject or ''
            frm = frm or row.from_addr or ''

    try:
        body_data = fetch_message_body(account, password, imap_folder, uid)
        body_text = _plain_from_body(body_data)
        sender = body_data.get('sender') or {}
        subj = subj or body_data.get('subject') or sender.get('subject') or ''
        frm = frm or sender.get('from_email') or sender.get('from_name') or ''
    except Exception as exc:
        return {'success': False, 'message': f'Mail içeriği okunamadı: {exc}'}

    if not body_text.strip():
        return {
            'success': False,
            'message': f'“{subj or "Mail"}” içeriği boş veya yalnızca ek dosyadan oluşuyor.',
        }

    prompt = (
        f'Konu: {subj}\nGönderen: {frm}\n\n'
        f'İçerik:\n{body_text[:9000]}\n\n'
        'Bu e-postayı Türkçe özetle (3-6 madde).'
    )
    try:
        out = chat_completion(
            api_key=cfg['api_key'],
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': _SUMMARY_SYSTEM},
                {'role': 'user', 'content': prompt},
            ],
            provider=cfg['provider'],
            timeout=60.0,
        )
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}

    summary = sanitize_ai_text(out['content'])
    if not is_meaningful_ai_text(summary, min_len=20):
        lines = [ln.strip() for ln in body_text.splitlines() if ln.strip()]
        preview = ' '.join(lines[:6])[:600]
        summary = (
            f'{subj or "Mail"} — AI özeti üretilemedi, kısa önizleme:\n\n'
            f'{preview}{"…" if len(body_text) > 600 else ""}'
        )

    header = subj or 'Mail'
    if frm:
        header = f'{header} ← {frm}'
    reply = f'{header}\n\n{summary}'

    return {
        'success': True,
        'summary': summary,
        'reply': reply,
        'subject': subj,
        'uid': uid,
        'folder': imap_folder,
    }


def try_mail_summary_reply(
    account,
    user_message: str,
    *,
    context: dict | None = None,
    password: str = '',
    chat_history: list[dict] | None = None,
) -> dict[str, Any] | None:
    if not is_mail_summary_request(user_message):
        return None

    target = resolve_summary_target(
        account,
        user_message,
        context=context,
        chat_history=chat_history,
    )
    if not target:
        subj = extract_subject_query(user_message)
        if subj:
            return {
                'success': True,
                'reply': f'“{subj}” konusunda mail bulunamadı. Konuyu kontrol edin veya maili listeden seçin.',
                'action': {'intent': 'chat'},
                'model': '',
            }
        return {
            'success': True,
            'reply': 'Hangi maili özetlememi istediğinizi söyleyin (ör. “Yazılım makalesi mailini özetle”) veya maili seçin.',
            'action': {'intent': 'chat'},
            'model': '',
        }

    uid, folder, subject = target
    ctx = context or {}
    out = summarize_message(
        account,
        password,
        uid=uid,
        folder=folder,
        subject=subject or ctx.get('selected_subject') or '',
        from_addr=ctx.get('selected_from') or ctx.get('context_from') or '',
    )
    if not out.get('success'):
        return {
            'success': True,
            'reply': out.get('message') or 'Özet oluşturulamadı.',
            'action': {'intent': 'chat'},
            'model': '',
        }

    return {
        'success': True,
        'reply': out['reply'],
        'action': {
            'intent': 'analyze',
            'uid': uid,
            'folder': folder,
            'summary': out.get('summary') or '',
            'match_subject': out.get('subject') or subject,
        },
        'executed': out,
        'model': out.get('model', ''),
    }
