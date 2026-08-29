"""AI akıllı yanıt — taslak üretimi ve arka plan gönderim."""
from __future__ import annotations

import re
from typing import Any

from webmail.ai.client import chat_completion
from webmail.ai.service import resolve_ai_config


def _reply_subject(original: str) -> str:
    subj = (original or '').strip()
    if not subj.lower().startswith('re:'):
        return f'Re: {subj}' if subj else 'Re:'
    return subj


def _extract_reply_to(from_addr: str, from_display: str = '') -> str:
    text = from_addr or from_display or ''
    m = re.search(r'[\w.+-]+@[\w.-]+\.\w+', text)
    return m.group(0).lower() if m else text.strip()


def generate_reply_draft(
    account,
    password: str,
    *,
    folder: str,
    uid: int,
    tone: str = 'professional',
    instruction: str = '',
    cached_subject: str = '',
    cached_from: str = '',
    cached_body: str = '',
) -> dict[str, Any]:
    """Seçili mail için yanıt taslağı üretir."""
    cfg = resolve_ai_config(account)
    if not cfg:
        return {'success': False, 'message': 'AI kullanılamıyor.'}

    subject = cached_subject
    from_addr = cached_from
    body_text = cached_body

    if password and uid > 0 and (not body_text or len(body_text) < 40):
        from webmail.imap_client import fetch_message_body, resolve_imap_folder

        try:
            imap_folder = resolve_imap_folder(account, password, folder)
            fetched = fetch_message_body(account, password, imap_folder, uid)
            body_text = fetched.get('plain') or ''
            if not body_text and fetched.get('html'):
                body_text = re.sub(r'<[^>]+>', ' ', fetched['html'])
        except Exception as exc:
            return {'success': False, 'message': f'Mail içeriği okunamadı: {exc}'}

    body_text = (body_text or '')[:8000]
    to_addr = _extract_reply_to(from_addr)
    if not to_addr or '@' not in to_addr:
        return {'success': False, 'message': 'Yanıt adresi çıkarılamadı.'}

    tone_map = {
        'professional': 'profesyonel ve nazik',
        'friendly': 'samimi',
        'brief': 'kısa ve net',
        'formal': 'resmi kurumsal',
    }
    tone_label = tone_map.get(tone, tone_map['professional'])

    user_prompt = (
        f"Aşağıdaki e-postaya {tone_label} Türkçe yanıt yaz.\n"
        f"Yalnızca yanıt gövdesini döndür (konu satırı ve imza hariç).\n"
        f"Gönderen: {from_addr}\nKonu: {subject}\n\nOrijinal mail:\n{body_text}\n"
    )
    if instruction:
        user_prompt += f"\nEk talimat: {instruction}\n"

    try:
        out = chat_completion(
            api_key=cfg['api_key'],
            model=cfg['model'],
            messages=[
                {
                    'role': 'system',
                    'content': (
                        cfg['system_prompt']
                        + '\nE-posta yanıtı yazıyorsun. Markdown kullanma. İmza ekleme.'
                    ),
                },
                {'role': 'user', 'content': user_prompt},
            ],
            provider=cfg['provider'],
            timeout=75.0,
        )
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}

    reply_body = (out['content'] or '').strip()
    return {
        'success': True,
        'to': to_addr,
        'subject': _reply_subject(subject),
        'body': reply_body,
        'body_html': f'<p>{reply_body.replace(chr(10), "</p><p>")}</p>',
        'tone': tone,
        'model': out.get('model'),
    }


def send_reply_draft(
    account,
    password: str,
    *,
    to: str,
    subject: str,
    body_text: str,
    body_html: str = '',
) -> dict[str, Any]:
    from webmail.outbound_queue import queue_outbound_send
    from webmail.send_validation import validate_outbound_recipients

    check = validate_outbound_recipients(account, to, '', '')
    if not check['ok']:
        return {'success': False, 'message': check['message']}
    if not password:
        return {'success': False, 'message': 'Oturum parolası yok.'}

    out = queue_outbound_send(
        account,
        password,
        to=to,
        subject=subject[:998],
        body_text=body_text,
        body_html=body_html or '',
    )
    out['message'] = out.get('message') or 'Yanıt arka planda gönderiliyor.'
    return out


def list_needs_reply(account, *, limit: int = 20) -> dict[str, Any]:
    from webmail.models import MailFolder, MailMessageCache

    inbox = MailFolder.objects.filter(account=account, name__iexact='INBOX').first()
    if not inbox:
        return {'success': True, 'items': []}

    items = []
    for row in MailMessageCache.objects.filter(folder=inbox, is_deleted=False).order_by('-date')[: limit * 2]:
        ai = row.ai_meta if isinstance(row.ai_meta, dict) else {}
        if not ai.get('needs_reply') and ai.get('priority') not in ('urgent', 'high'):
            continue
        items.append({
            'uid': row.uid,
            'subject': row.subject,
            'from_addr': row.from_addr,
            'date': row.date.isoformat() if row.date else None,
            'summary': ai.get('summary') or row.snippet,
            'priority': ai.get('priority'),
            'has_draft': bool(ai.get('reply_draft')),
            'reply_draft_preview': (ai.get('reply_draft') or '')[:200],
        })
        if len(items) >= limit:
            break
    return {'success': True, 'items': items, 'total': len(items)}
