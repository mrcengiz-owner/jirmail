"""AI posta ajanı — triage, organize, digest, kural motoru."""
from __future__ import annotations

import json
import logging
import re
from datetime import timedelta
from typing import Any

from django.utils import timezone

from webmail.ai.client import chat_completion, sanitize_ai_text
from webmail.ai.service import resolve_ai_config

logger = logging.getLogger(__name__)

_CATEGORIES = (
    'personal', 'work', 'finance', 'newsletter', 'promo',
    'spam', 'transactional', 'support', 'other',
)
_PRIORITIES = ('low', 'normal', 'high', 'urgent')
_ACTIONS = ('none', 'archive', 'spam', 'reply', 'star', 'move', 'mark_read')

_TRIAGE_PROMPT = (
    'Aşağıdaki e-postayı analiz et. Yalnızca JSON döndür (markdown yok):\n'
    '{"category":"...", "priority":"...", "needs_reply":false, '
    '"suggested_action":"none", "move_to":"", "summary":"...", '
    '"reply_draft":"", "confidence":0.0}\n'
    f'category: {", ".join(_CATEGORIES)}\n'
    f'priority: {", ".join(_PRIORITIES)}\n'
    f'suggested_action: {", ".join(_ACTIONS)}\n'
    'confidence: 0.0-1.0 (spam/archive kararları için yüksek olmalı)'
)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or '').strip()
    m = re.search(r'\{[\s\S]*\}', text)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def _normalize_triage(raw: dict) -> dict[str, Any]:
    cat = (raw.get('category') or 'other').lower()
    if cat not in _CATEGORIES:
        cat = 'other'
    pri = (raw.get('priority') or 'normal').lower()
    if pri not in _PRIORITIES:
        pri = 'normal'
    act = (raw.get('suggested_action') or 'none').lower()
    if act not in _ACTIONS:
        act = 'none'
    try:
        conf = float(raw.get('confidence') or 0)
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    return {
        'category': cat,
        'priority': pri,
        'needs_reply': bool(raw.get('needs_reply')),
        'suggested_action': act,
        'move_to': (raw.get('move_to') or '').strip(),
        'summary': (raw.get('summary') or '')[:500],
        'reply_draft': (raw.get('reply_draft') or '')[:4000],
        'confidence': conf,
        'triaged_at': timezone.now().isoformat(),
    }


def get_or_create_agent_profile(account):
    from webmail.models import MailAgentProfile

    profile, _ = MailAgentProfile.objects.get_or_create(account=account)
    return profile


def triage_message_content(
    account,
    *,
    subject: str,
    from_addr: str,
    snippet: str,
    body_text: str = '',
) -> dict[str, Any]:
    cfg = resolve_ai_config(account)
    if not cfg:
        return {'success': False, 'message': 'AI kullanılamıyor'}

    if is_vip_sender(account, from_addr):
        snippet = f'[VIP gönderen] {snippet}'

    blob = (
        f"Konu: {subject}\nGönderen: {from_addr}\n"
        f"Önizleme: {snippet}\n"
        f"İçerik:\n{(body_text or snippet)[:6000]}"
    )
    try:
        out = chat_completion(
            api_key=cfg['api_key'],
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': cfg['system_prompt'] + '\n' + _TRIAGE_PROMPT},
                {'role': 'user', 'content': blob},
            ],
            provider=cfg['provider'],
            timeout=60.0,
        )
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}

    meta = _normalize_triage(_parse_json_object(out['content']))
    if is_vip_sender(account, from_addr) and meta.get('priority') not in ('urgent', 'high'):
        meta['priority'] = 'high'
        meta['vip'] = True
    return {'success': True, 'ai_meta': meta}


def is_vip_sender(account, from_addr: str) -> bool:
    from webmail.models import MailVipSender

    addr = (from_addr or '').strip().lower()
    if not addr:
        return False
    for row in MailVipSender.objects.filter(account=account, enabled=True):
        pat = (row.pattern or '').strip().lower()
        if not pat:
            continue
        if pat.startswith('@') and addr.endswith(pat):
            return True
        if pat in addr or addr == pat:
            return True
    return False


def _queue_or_apply_action(
    account,
    password: str,
    *,
    row,
    action: dict,
    profile,
    autopilot: bool,
    source: str,
) -> tuple[str, dict | None]:
    """Returns ('applied'|'queued'|'suggested', detail)."""
    from webmail.ai.approval import create_pending_action, is_risky_action

    act_type = action.get('action_type') or action.get('action') or ''
    act_target = action.get('action_target') or ''
    reason = f"{source}: {act_type}"

    if autopilot and not is_risky_action(act_type):
        res = execute_imap_action(
            account,
            password,
            folder='INBOX',
            uid=row.uid,
            action_type=act_type,
            action_target=act_target,
        )
        if res.get('success'):
            return 'applied', {'uid': row.uid, 'action': action, 'source': source}
        return 'suggested', {'uid': row.uid, 'error': res.get('message')}

    # Assist modu veya riskli aksiyon → onay kuyruğu
    from webmail.models import MailAgentProfile

    if profile.mode == MailAgentProfile.MODE_ASSIST or is_risky_action(act_type):
        out = create_pending_action(
            account,
            uid=row.uid,
            folder='INBOX',
            action_type=act_type,
            action_target=act_target,
            subject=row.subject or '',
            from_addr=row.from_addr or '',
            reason=reason,
            source=source,
        )
        if out.get('success'):
            return 'queued', {'uid': row.uid, 'action': action, 'pending_id': out.get('id')}

    return 'suggested', {
        'uid': row.uid,
        'subject': row.subject,
        'action': action,
    }


def apply_rules_to_message(account, msg_row) -> dict[str, Any] | None:
    from webmail.models import MailAiRule

    rules = MailAiRule.objects.filter(account=account, enabled=True).order_by('priority', 'id')
    subj = (msg_row.subject or '').lower()
    frm = (msg_row.from_addr or '').lower()
    ai = msg_row.ai_meta if isinstance(getattr(msg_row, 'ai_meta', None), dict) else {}

    for rule in rules:
        if rule.match_from and rule.match_from.lower() not in frm:
            continue
        if rule.match_subject and rule.match_subject.lower() not in subj:
            continue
        if rule.match_category and rule.match_category != ai.get('category'):
            continue
        return {
            'rule_id': rule.id,
            'rule_name': rule.name,
            'action_type': rule.action_type,
            'action_target': rule.action_target,
        }
    return None


def execute_imap_action(
    account,
    password: str,
    *,
    folder: str,
    uid: int,
    action_type: str,
    action_target: str = '',
) -> dict[str, Any]:
    from webmail.imap_client import delete_message, move_message, resolve_imap_folder, set_flag
    from webmail.models import MailFolder, MailMessageCache

    imap_folder = resolve_imap_folder(account, password, folder)
    folder_obj = MailFolder.objects.filter(account=account, name=imap_folder).first()

    act = (action_type or '').lower()
    try:
        if act in ('spam', 'move_spam'):
            target = resolve_imap_folder(account, password, 'Junk')
            move_message(account, password, imap_folder, uid, target)
        elif act == 'archive':
            target = resolve_imap_folder(account, password, 'Archive')
            move_message(account, password, imap_folder, uid, target)
        elif act == 'move_folder' and action_target:
            target = resolve_imap_folder(account, password, action_target)
            move_message(account, password, imap_folder, uid, target)
        elif act == 'delete':
            delete_message(account, password, imap_folder, uid)
        elif act == 'mark_read':
            set_flag(account, password, imap_folder, uid, '\\Seen', add=True)
            if folder_obj:
                MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_seen=True)
        elif act in ('star', 'flag'):
            set_flag(account, password, imap_folder, uid, '\\Flagged', add=True)
            if folder_obj:
                MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_flagged=True)
        elif act == 'not_spam':
            target = resolve_imap_folder(account, password, 'INBOX')
            move_message(account, password, imap_folder, uid, target)
        else:
            return {'success': False, 'message': f'Bilinmeyen aksiyon: {act}'}

        if act in ('spam', 'archive', 'move_folder', 'delete', 'not_spam') and folder_obj:
            MailMessageCache.objects.filter(folder=folder_obj, uid=uid).update(is_deleted=True)
        return {'success': True, 'action': act}
    except Exception as exc:
        logger.warning('IMAP action %s uid=%s: %s', act, uid, exc)
        return {'success': False, 'message': str(exc)}


def _action_from_ai_meta(meta: dict, autopilot: bool) -> dict | None:
    if not meta:
        return None
    act = meta.get('suggested_action') or 'none'
    conf = float(meta.get('confidence') or 0)
    if act == 'none':
        return None
    if not autopilot:
        return None
    threshold = 0.82 if act in ('spam', 'archive', 'mark_read') else 0.92
    if conf < threshold:
        return None
    if act == 'move' and meta.get('move_to'):
        return {'action_type': 'move_folder', 'action_target': meta['move_to']}
    if act == 'spam':
        return {'action_type': 'spam'}
    if act == 'archive':
        return {'action_type': 'archive'}
    if act == 'mark_read':
        return {'action_type': 'mark_read'}
    if act == 'star':
        return {'action_type': 'star'}
    return None


def triage_cache_row(account, password: str, msg_row, *, fetch_body: bool = False) -> dict[str, Any]:
    from webmail.imap_client import fetch_message_body, resolve_imap_folder

    body_text = ''
    if fetch_body and password:
        try:
            folder = resolve_imap_folder(account, password, 'INBOX')
            body = fetch_message_body(account, password, folder, msg_row.uid)
            body_text = body.get('plain') or ''
            if not body_text and body.get('html'):
                body_text = re.sub(r'<[^>]+>', ' ', body['html'])
        except Exception:
            pass

    out = triage_message_content(
        account,
        subject=msg_row.subject or '',
        from_addr=msg_row.from_addr or '',
        snippet=msg_row.snippet or '',
        body_text=body_text,
    )
    if not out.get('success'):
        return out

    meta = out['ai_meta']
    msg_row.ai_meta = meta
    msg_row.save(update_fields=['ai_meta'])
    return {'success': True, 'uid': msg_row.uid, 'ai_meta': meta}


def batch_triage_inbox(account, password: str, *, limit: int = 20) -> dict[str, Any]:
    from webmail.models import MailFolder, MailMessageCache

    inbox = MailFolder.objects.filter(account=account, name__iexact='INBOX').first()
    if not inbox:
        return {'success': False, 'message': 'INBOX cache yok — önce senkronize edin.'}

    rows = (
        MailMessageCache.objects.filter(folder=inbox, is_deleted=False)
        .order_by('-date', '-uid')[: limit * 3]
    )
    triaged = []
    errors = []
    count = 0
    for row in rows:
        if count >= limit:
            break
        ai = row.ai_meta if isinstance(row.ai_meta, dict) else {}
        if ai.get('triaged_at'):
            continue
        r = triage_cache_row(account, password, row, fetch_body=not row.is_seen)
        if r.get('success'):
            triaged.append(r)
            count += 1
        else:
            errors.append({'uid': row.uid, 'error': r.get('message')})
    return {'success': True, 'triaged': len(triaged), 'items': triaged, 'errors': errors}


def organize_inbox(account, password: str, *, limit: int = 25, autopilot: bool = False) -> dict[str, Any]:
    from webmail.models import MailAgentProfile, MailFolder, MailMessageCache

    profile = get_or_create_agent_profile(account)
    autopilot = autopilot or profile.mode == MailAgentProfile.MODE_AUTOPILOT

    inbox = MailFolder.objects.filter(account=account, name__iexact='INBOX').first()
    if not inbox:
        return {'success': False, 'message': 'INBOX yok'}

    rows = MailMessageCache.objects.filter(folder=inbox, is_deleted=False).order_by('-date')[:limit]
    applied = []
    queued = []
    suggestions = []

    for row in rows:
        rule_hit = apply_rules_to_message(account, row)
        action = rule_hit
        ai = row.ai_meta if isinstance(row.ai_meta, dict) else {}
        if not action:
            ai_action = _action_from_ai_meta(ai, autopilot)
            if ai_action:
                action = ai_action
            elif ai.get('suggested_action') not in (None, '', 'none') and profile.mode == MailAgentProfile.MODE_ASSIST:
                sa = ai.get('suggested_action')
                action = {
                    'action_type': 'spam' if sa == 'spam' else ('archive' if sa == 'archive' else sa),
                    'action_target': ai.get('move_to') or '',
                }

        if not action:
            continue

        kind, detail = _queue_or_apply_action(
            account,
            password,
            row=row,
            action=action,
            profile=profile,
            autopilot=autopilot,
            source='rule' if rule_hit else 'ai',
        )
        if kind == 'applied' and detail:
            applied.append(detail)
        elif kind == 'queued' and detail:
            queued.append(detail)
        elif kind == 'suggested' and detail:
            suggestions.append(detail)

    profile.last_organize_at = timezone.now()
    profile.save(update_fields=['last_organize_at'])
    return {
        'success': True,
        'applied': applied,
        'queued': queued,
        'suggestions': suggestions,
        'autopilot': autopilot,
    }


def _local_digest_text(rows, urgent_lines: list, needs_reply_lines: list) -> str:
    """AI yanıt vermezse yerel özet."""
    if not rows:
        return 'Gelen kutunuz boş — özetlenecek mail yok. Senkronize butonuna basıp tekrar deneyin.'
    parts = [f'Gelen kutusunda {len(rows)} mesaj var.', '']
    if urgent_lines:
        parts.append('Acil / yüksek öncelik:')
        for line in urgent_lines[:8]:
            parts.append('• ' + line.lstrip('- '))
        parts.append('')
    if needs_reply_lines:
        parts.append('Yanıt bekleyen:')
        for line in needs_reply_lines[:8]:
            parts.append('• ' + line.lstrip('- '))
        parts.append('')
    parts.append('Son mesajlar:')
    for r in rows[:12]:
        subj = r.subject or '(konu yok)'
        frm = r.from_addr or '?'
        parts.append(f'• {subj} ← {frm}')
    return '\n'.join(parts)


def build_inbox_digest_reply(account, *, password: str = '', force_refresh: bool = False) -> dict[str, Any]:
    """Özet isteği — önbellek, AI veya yerel liste."""
    from webmail.models import MailFolder, MailMessageCache

    profile = get_or_create_agent_profile(account)
    if not force_refresh and profile.last_digest_text:
        cached = sanitize_ai_text(profile.last_digest_text)
        if cached:
            return {
                'success': True,
                'digest': cached,
                'reply': cached,
                'cached': True,
            }

    inbox = MailFolder.objects.filter(account=account, name__iexact='INBOX').first()
    if not inbox:
        return {'success': False, 'message': 'Gelen kutusu henüz senkronize edilmemiş. Yenile butonuna basın.'}

    rows = list(
        MailMessageCache.objects.filter(folder=inbox, is_deleted=False).order_by('-date')[:40]
    )
    urgent = []
    needs_reply = []
    for r in rows:
        ai = r.ai_meta if isinstance(r.ai_meta, dict) else {}
        pri = ai.get('priority') or 'normal'
        line = f"- [{pri}] {r.subject or '(konu yok)'} ← {r.from_addr or '?'}"
        if ai.get('summary'):
            line += f" — {ai['summary'][:120]}"
        if pri in ('urgent', 'high'):
            urgent.append(line)
        if ai.get('needs_reply'):
            needs_reply.append(line)

    if password and rows:
        ai_out = generate_inbox_digest(account, password)
        if ai_out.get('success'):
            text = sanitize_ai_text(ai_out.get('digest') or '')
            if text:
                return {**ai_out, 'reply': text}
        local = _local_digest_text(rows, urgent, needs_reply)
        return {
            'success': True,
            'digest': local,
            'reply': local,
            'stats': ai_out.get('stats') if ai_out.get('success') else {'total': len(rows)},
            'fallback': True,
        }

    local = _local_digest_text(rows, urgent, needs_reply)
    return {
        'success': True,
        'digest': local,
        'reply': local,
        'stats': {'total': len(rows)},
        'fallback': True,
    }


def generate_inbox_digest(account, password: str) -> dict[str, Any]:
    from webmail.models import MailFolder, MailMessageCache

    cfg = resolve_ai_config(account)
    if not cfg:
        return {'success': False, 'message': 'AI kullanılamıyor'}

    inbox = MailFolder.objects.filter(account=account, name__iexact='INBOX').first()
    if not inbox:
        return {'success': False, 'message': 'INBOX yok'}

    rows = list(
        MailMessageCache.objects.filter(folder=inbox, is_deleted=False)
        .order_by('-date')[:40]
    )
    lines = []
    urgent = []
    needs_reply = []
    for r in rows:
        ai = r.ai_meta if isinstance(r.ai_meta, dict) else {}
        pri = ai.get('priority') or 'normal'
        line = f"- [{pri}] {r.subject or '(konu yok)'} ← {r.from_addr or '?'}"
        if ai.get('summary'):
            line += f" — {ai['summary'][:120]}"
        lines.append(line)
        if pri in ('urgent', 'high'):
            urgent.append(line)
        if ai.get('needs_reply'):
            needs_reply.append(line)

    prompt = (
        'Gelen kutusu için Türkçe günlük brifing yaz (madde madde, kısa).\n'
        f'Toplam {len(rows)} mesaj.\n'
        f'Acil/yüksek öncelik ({len(urgent)}):\n' + '\n'.join(urgent[:12] or ['(yok)']) + '\n'
        f'Yanıt bekleyen ({len(needs_reply)}):\n' + '\n'.join(needs_reply[:12] or ['(yok)']) + '\n'
        'Son mesajlar:\n' + '\n'.join(lines[:25])
    )
    try:
        out = chat_completion(
            api_key=cfg['api_key'],
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': cfg['system_prompt']},
                {'role': 'user', 'content': prompt},
            ],
            provider=cfg['provider'],
            timeout=90.0,
        )
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}

    profile = get_or_create_agent_profile(account)
    profile.last_digest_at = timezone.now()
    text = sanitize_ai_text(out['content'])
    if not text:
        text = _local_digest_text(rows, urgent, needs_reply)
    profile.last_digest_text = text[:12000]
    profile.save(update_fields=['last_digest_at', 'last_digest_text'])

    return {
        'success': True,
        'digest': text,
        'stats': {
            'total': len(rows),
            'urgent': len(urgent),
            'needs_reply': len(needs_reply),
        },
    }


def run_agent_cycle(
    account,
    password: str,
    *,
    triage: bool = True,
    organize: bool = True,
    digest: bool = False,
) -> dict[str, Any]:
    from webmail.models import MailAgentProfile

    profile = get_or_create_agent_profile(account)
    if profile.mode == MailAgentProfile.MODE_OFF:
        return {'success': False, 'message': 'AI ajan kapalı'}

    result: dict[str, Any] = {'success': True, 'steps': {}}

    if triage and profile.auto_triage:
        result['steps']['triage'] = batch_triage_inbox(
            account, password, limit=profile.triage_batch_size,
        )
        profile.last_triage_at = timezone.now()
        profile.save(update_fields=['last_triage_at'])

    if organize and profile.auto_organize:
        result['steps']['organize'] = organize_inbox(
            account,
            password,
            limit=profile.organize_batch_size,
            autopilot=(profile.mode == MailAgentProfile.MODE_AUTOPILOT),
        )

    if digest and profile.digest_enabled:
        result['steps']['digest'] = generate_inbox_digest(account, password)

    from webmail.sse import publish_agent_event

    publish_agent_event(account.id, 'agent_cycle_complete', result)
    return result
