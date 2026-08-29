"""Hesap + domain AI ayarları ve sohbet / komut işleme."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from webmail.ai.client import chat_completion, sanitize_ai_text, is_meaningful_ai_text

_GREETING = frozenset({'merhaba', 'selam', 'hey', 'hi', 'hello', 'günaydın', 'iyi günler'})


def _is_digest_request(message: str) -> bool:
    from webmail.ai.mail_summary import is_inbox_digest_request

    return is_inbox_digest_request(message)


def _is_pure_greeting(message: str) -> bool:
    """Yalnızca selam — özet/komut içermeyen kısa mesaj."""
    text = (message or '').strip()
    if not text:
        return False
    if _is_digest_request(text):
        return False
    low = re.sub(r'[^\w\s]', '', text.lower()).strip()
    if low in _GREETING:
        return True
    words = low.split()
    return len(words) <= 2 and words[0] in _GREETING and len(words) == 1

_AGENT_SYSTEM_SUFFIX = (
    '\n\nSen Jîr-Mail posta ajanısın. Gelen/giden postayı analiz eder, sınıflandırır, '
    'organize eder, taslak yazar, gönderim/planlama önerirsin. Türkçe yanıt ver.\n'
    'Asla "User Safety", moderation etiketi veya tek satırlık meta yanıt verme.\n'
    'Yanıtını JSON bloğu ile bitir:\n'
    '```json\n'
    '{"intent":"chat|send_mail|schedule_mail|reply|analyze|archive|spam|move|'
    'mark_read|organize_inbox|run_agent|create_rule|digest|triage_inbox|batch_move",'
    '"to":"","subject":"","body":"","send_at":"","summary":"",'
    '"uid":0,"folder":"INBOX","move_to":"","match_from":"","match_subject":"",'
    '"rule_name":"","action_type":"move_folder"}\n'
    '```\n'
    'Örnekler:\n'
    '- "paribu maillerini finans klasörüne taşı" → intent batch_move, match_from paribu, move_to finans\n'
    '- "bunu arşivle" → intent archive (seçili mail uid bağlamdan)\n'
    '- "gelen kutusunu düzenle" → intent organize_inbox\n'
    '- "bugünkü özeti ver" / "gelen kutusu özeti" → intent digest\n'
    '- "X mailini özetle" / "içeriğin özetini getir" → intent analyze (tek mail)\n'
    'move_to: hedef klasör etiketi veya IMAP adı. batch_move: gönderene göre toplu taşıma.'
)


def resolve_ai_config(account) -> dict[str, Any] | None:
    account = (
        type(account).objects.select_related('domain').filter(pk=account.pk).first()
        if hasattr(account, 'pk') else account
    )
    if not account or not account.ai_available:
        return None
    domain = account.domain
    api_key = (account.ai_api_key or '').strip()
    if not api_key:
        return None
    return {
        'api_key': api_key,
        'provider': (account.ai_provider or domain.ai_provider or 'openrouter').strip(),
        'model': (account.ai_model or domain.ai_default_model or 'openai/gpt-4o-mini').strip(),
        'system_prompt': (
            account.ai_system_prompt
            or domain.ai_system_prompt_default
            or 'Sen e-posta asistanısın.'
        ).strip(),
    }


def _build_context_block(ctx: dict | None) -> str:
    if not ctx:
        return ''
    parts = []
    if ctx.get('selected_subject'):
        parts.append(f"Seçili mail konusu: {ctx['selected_subject']}")
    if ctx.get('selected_from'):
        parts.append(f"Gönderen: {ctx['selected_from']}")
    if ctx.get('selected_body'):
        body = str(ctx['selected_body'])[:6000]
        parts.append(f"Seçili mail içeriği:\n{body}")
    if ctx.get('inbox_summary'):
        parts.append(f"Gelen kutusu özeti:\n{ctx['inbox_summary']}")
    if ctx.get('account_email'):
        parts.append(f"Kullanıcı adresi: {ctx['account_email']}")
    if ctx.get('folders'):
        parts.append(f"Kullanılabilir klasörler:\n{ctx['folders']}")
    if ctx.get('selected_uid'):
        parts.append(f"Seçili mail uid: {ctx['selected_uid']}")
    if ctx.get('selected_folder'):
        parts.append(f"Seçili mail klasörü: {ctx['selected_folder']}")
    return '\n'.join(parts)


def _fallback_reply(user_message: str) -> str:
    low = (user_message or '').strip().lower()
    if low in _GREETING:
        return (
            'Merhaba! Gelen kutunuzu düzenleyebilir, özet alabilir, taslak yazabilir '
            'veya mailleri klasörlere taşıyabilirim. Örneğin: "Bugünkü özeti ver" '
            'veya "Gelen kutusunu düzenle".'
        )
    return 'Size nasıl yardımcı olabilirim? Özet, sınıflandırma, taslak veya klasör işlemi isteyebilirsiniz.'


def _try_digest_reply(account, user_message: str, *, password: str = '') -> dict[str, Any] | None:
    if not _is_digest_request(user_message):
        return None
    from webmail.ai.agent import build_inbox_digest_reply

    out = build_inbox_digest_reply(account, password=password or '', force_refresh=True)
    reply = sanitize_ai_text(out.get('digest') or out.get('reply') or '')
    if reply and not is_meaningful_ai_text(reply):
        reply = ''
    if not reply and out.get('success'):
        reply = out.get('message') or ''
    if reply:
        return {
            'success': True,
            'reply': reply,
            'action': {'intent': 'digest'},
            'executed': out if out.get('success') else None,
            'model': '',
        }
    err = out.get('message') or 'Özet oluşturulamadı. Gelen kutusunu senkronize edip tekrar deneyin.'
    return {
        'success': True,
        'reply': err,
        'action': {'intent': 'digest'},
        'model': '',
    }


_AUTO_EXECUTE = frozenset({
    'organize_inbox', 'run_agent', 'triage_inbox', 'batch_move', 'create_folder',
    'archive', 'spam', 'mark_read', 'move', 'create_rule', 'digest',
})


def _enrich_action(action: dict[str, Any], ctx: dict | None) -> dict[str, Any]:
    ctx = ctx or {}
    out = dict(action)
    intent = (out.get('intent') or 'chat').lower()
    if intent in ('move', 'archive', 'spam', 'mark_read', 'reply') and not out.get('uid'):
        uid = int(ctx.get('selected_uid') or 0)
        if uid:
            out['uid'] = uid
            out.setdefault('folder', ctx.get('selected_folder') or 'INBOX')
    if intent == 'move' and not out.get('move_to') and out.get('action_target'):
        out['move_to'] = out['action_target']
    if intent == 'batch_move' and not out.get('folder'):
        out['folder'] = ctx.get('selected_folder') or 'INBOX'
    return out


def _resolve_move_target(account, password: str, action: dict[str, Any]) -> dict[str, Any]:
    from webmail.ai.nl_commands import resolve_folder_label

    intent = (action.get('intent') or '').lower()
    if intent not in ('move', 'batch_move'):
        return action
    label = action.get('move_to') or action.get('action_target') or ''
    if not label:
        return action
    resolved = resolve_folder_label(
        account,
        label,
        create_if_missing=bool(action.get('create_folder')),
        password=password,
    )
    if resolved:
        action['move_to'] = resolved
        action['action_target'] = resolved
    return action


def ai_chat(
    account,
    user_message: str,
    *,
    context: dict | None = None,
    password: str = '',
    chat_history: list[dict] | None = None,
) -> dict[str, Any]:
    cfg = resolve_ai_config(account)
    if not cfg:
        return {
            'success': False,
            'message': 'AI bu hesap için kapalı veya API anahtarı yok (domain ayarlarını kontrol edin).',
        }

    hist = list(chat_history or [])

    from webmail.ai.mail_summary import try_mail_summary_reply

    mail_summary_out = try_mail_summary_reply(
        account,
        user_message,
        context=context,
        password=password,
        chat_history=hist,
    )
    if mail_summary_out:
        return mail_summary_out

    digest_out = _try_digest_reply(account, user_message, password=password)
    if digest_out:
        return digest_out

    if _is_pure_greeting(user_message):
        return {
            'success': True,
            'reply': _fallback_reply(user_message),
            'action': {'intent': 'chat'},
            'model': '',
        }

    ctx = dict(context or {})
    ctx.setdefault('account_email', getattr(account, 'email', ''))

    from webmail.ai.nl_commands import try_nl_command

    nl_out = try_nl_command(account, user_message, context=ctx, password=password)
    if nl_out and nl_out.get('handled'):
        return {
            'success': True,
            'reply': nl_out.get('reply') or 'Tamam.',
            'action': nl_out.get('action') or {'intent': 'chat'},
            'executed': nl_out.get('executed'),
            'model': '',
        }

    ctx = dict(context or {})
    ctx.setdefault('account_email', getattr(account, 'email', ''))
    if not ctx.get('folders'):
        from webmail.models import MailFolder
        from webmail.imap_client import is_standard_folder_name

        rows = MailFolder.objects.filter(account=account).order_by('name')[:40]
        folder_lines = []
        for row in rows:
            kind = 'standart' if is_standard_folder_name(row.name) else 'özel'
            folder_lines.append(f"- {row.name} ({kind})")
        if folder_lines:
            ctx['folders'] = '\n'.join(folder_lines)
    system = cfg['system_prompt'] + _AGENT_SYSTEM_SUFFIX
    ctx_block = _build_context_block(ctx)
    if ctx_block:
        system += '\n\n--- Bağlam ---\n' + ctx_block

    messages = [{'role': 'system', 'content': system}]
    for turn in hist[-10:]:
        role = (turn.get('role') or '').lower()
        text = sanitize_ai_text(turn.get('text') or turn.get('content') or '')
        if role in ('user', 'assistant') and text:
            messages.append({'role': role, 'content': text[:2500]})
    messages.append({'role': 'user', 'content': user_message})
    try:
        out = chat_completion(
            api_key=cfg['api_key'],
            model=cfg['model'],
            messages=messages,
            provider=cfg['provider'],
        )
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}

    content = out['content']
    action = _enrich_action(_parse_action_json(content), ctx)
    reply = sanitize_ai_text(_strip_json_block(content))
    if not reply:
        reply = _fallback_reply(user_message)
    if action.get('summary') and action.get('intent') == 'analyze':
        reply = action['summary'] if not reply or reply == _fallback_reply(user_message) else reply

    executed = None
    intent = (action.get('intent') or 'chat').lower()
    if password and intent in _AUTO_EXECUTE:
        run_action = _resolve_move_target(account, password, dict(action))
        executed = execute_ai_action(account, password, run_action)
        if executed.get('success') and executed.get('message'):
            extra = executed['message']
            if extra not in reply:
                reply = f'{reply}\n\n{extra}'.strip()

    return {
        'success': True,
        'reply': reply,
        'action': action,
        'executed': executed,
        'model': out['model'],
    }


def ai_analyze_message(
    account,
    *,
    subject: str = '',
    from_addr: str = '',
    body_text: str = '',
) -> dict[str, Any]:
    prompt = (
        'Bu e-postayı analiz et: özet, aciliyet (düşük/orta/yüksek), '
        'olası spam/dolandırıcılık riski, önerilen aksiyon (yanıtla/ignore/spam).'
        f'\nKonu: {subject}\nGönderen: {from_addr}\nİçerik:\n{body_text[:8000]}'
    )
    return ai_chat(
        account,
        prompt,
        context={
            'selected_subject': subject,
            'selected_from': from_addr,
            'selected_body': body_text,
            'account_email': getattr(account, 'email', ''),
        },
    )


def execute_ai_action(account, password: str, action: dict[str, Any]) -> dict[str, Any]:
    """AI intent JSON'unu gerçek posta işlemine çevirir."""
    intent = (action.get('intent') or 'chat').lower()
    if intent == 'chat':
        return {'success': True, 'message': 'Sohbet yanıtı.', 'intent': intent}
    if intent == 'analyze':
        return {'success': True, 'intent': intent, 'summary': action.get('summary') or ''}

    if intent == 'schedule_mail':
        from webmail.models import ScheduledMail

        send_at = action.get('send_at_parsed')
        if not send_at:
            raw = action.get('send_at') or ''
            try:
                send_at = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            except Exception:
                send_at = timezone.now() + timedelta(hours=1)
        to_addr = (action.get('to') or '').strip()
        if not to_addr:
            return {'success': False, 'message': 'Planlı gönderim için alıcı gerekli.'}
        row = ScheduledMail.objects.create(
            account=account,
            to_addr=to_addr,
            subject=(action.get('subject') or '')[:998],
            body_text=action.get('body') or '',
            body_html='',
            send_at=send_at,
        )
        return {
            'success': True,
            'intent': intent,
            'scheduled_id': row.id,
            'send_at': row.send_at.isoformat(),
            'message': f'Gönderim planlandı: {row.send_at.strftime("%d.%m.%Y %H:%M")}',
        }

    if intent in ('send_mail', 'reply'):
        from webmail.outbound_queue import queue_outbound_send
        from webmail.send_validation import validate_outbound_recipients

        to_addr = (action.get('to') or '').strip()
        subject = (action.get('subject') or '')[:998]
        body = action.get('body') or ''
        if not to_addr:
            return {'success': False, 'message': 'Gönderim için alıcı gerekli.'}
        if not password:
            return {'success': False, 'message': 'Oturum parolası yok — yeniden giriş yapın.'}
        check = validate_outbound_recipients(account, to_addr, '', '')
        if not check['ok']:
            return {'success': False, 'message': check['message']}
        out = queue_outbound_send(
            account,
            password,
            to=to_addr,
            subject=subject,
            body_text=body,
            body_html='',
        )
        out['intent'] = intent
        return out

    if intent in ('archive', 'spam', 'mark_read', 'move'):
        from webmail.ai.agent import execute_imap_action

        uid = int(action.get('uid') or 0)
        if not uid or not password:
            return {'success': False, 'message': 'uid ve oturum parolası gerekli.'}
        folder = action.get('folder') or 'INBOX'
        act_map = {
            'archive': 'archive',
            'spam': 'spam',
            'mark_read': 'mark_read',
            'move': 'move_folder',
        }
        run = _resolve_move_target(account, password, dict(action))
        target = run.get('move_to') or run.get('action_target') or ''
        return execute_imap_action(
            account,
            password,
            folder=folder,
            uid=uid,
            action_type=act_map.get(intent, intent),
            action_target=target,
        )

    if intent == 'batch_move':
        from webmail.ai.nl_commands import batch_move_messages

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        run = _resolve_move_target(account, password, dict(action))
        return batch_move_messages(account, password, run)

    if intent == 'triage_inbox':
        from webmail.ai.agent import batch_triage_inbox

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        out = batch_triage_inbox(account, password, limit=int(action.get('limit') or 25))
        if out.get('success'):
            out['message'] = f'{out.get("triaged", 0)} mail sınıflandırıldı.'
        return out

    if intent == 'digest':
        from webmail.ai.agent import build_inbox_digest_reply

        out = build_inbox_digest_reply(
            account,
            password=password,
            force_refresh=bool(action.get('refresh')),
        )
        text = sanitize_ai_text(out.get('digest') or out.get('reply') or '')
        if text and is_meaningful_ai_text(text):
            return {
                'success': True,
                'intent': intent,
                'digest': text,
                'message': text,
            }
        return {'success': False, 'message': out.get('message') or 'Özet oluşturulamadı.'}

    if intent == 'create_folder':
        from webmail.imap_client import create_imap_folder, folder_display_name
        from webmail.models import MailFolder

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        name = (action.get('name') or action.get('folder_name') or '').strip()
        if not name:
            return {'success': False, 'message': 'Klasör adı gerekli.'}
        try:
            imap_name = create_imap_folder(account, password, name)
        except ValueError as exc:
            return {'success': False, 'message': str(exc)}
        MailFolder.objects.update_or_create(
            account=account,
            name=imap_name,
            defaults={'display_name': folder_display_name(imap_name)},
        )
        label = folder_display_name(imap_name)
        return {
            'success': True,
            'intent': intent,
            'folder': imap_name,
            'message': f'Klasör oluşturuldu: {label}',
        }

    if intent == 'organize_inbox':
        from webmail.ai.agent import organize_inbox

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        out = organize_inbox(account, password, autopilot=False)
        if out.get('success'):
            n = len(out.get('applied') or [])
            q = len(out.get('queued') or [])
            out['message'] = f'Gelen kutusu düzenlendi: {n} uygulandı, {q} onay bekliyor.'
        return out

    if intent == 'run_agent':
        from webmail.ai.agent import run_agent_cycle

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        out = run_agent_cycle(account, password, triage=True, organize=True, digest=False)
        if out.get('success'):
            out['message'] = out.get('message') or 'AI ajan döngüsü tamamlandı.'
        return out

    if intent == 'create_rule':
        from webmail.models import MailAiRule

        name = (action.get('rule_name') or action.get('name') or 'AI kuralı')[:120]
        target = (action.get('action_target') or action.get('move_to') or '').strip()
        if target and password:
            resolved = _resolve_move_target(account, password, {
                'intent': 'move',
                'move_to': target,
                'create_folder': action.get('create_folder', True),
            })
            target = resolved.get('move_to') or resolved.get('action_target') or target
        row = MailAiRule.objects.create(
            account=account,
            name=name,
            match_from=(action.get('match_from') or '')[:255],
            match_subject=(action.get('match_subject') or '')[:255],
            match_category=(action.get('match_category') or '')[:32],
            action_type=(action.get('action_type') or MailAiRule.ACTION_ARCHIVE)[:32],
            action_target=target[:255],
            created_by_ai=True,
        )
        return {'success': True, 'intent': intent, 'rule_id': row.id, 'message': f'Kural oluşturuldu: {name}'}

    return {'success': False, 'message': f'Bilinmeyen intent: {intent}'}


def create_ai_task(account, instruction: str, *, task_type: str = 'custom', context: dict | None = None):
    from webmail.models import MailAiTask

    return MailAiTask.objects.create(
        account=account,
        instruction=instruction,
        task_type=task_type,
        context=context or {},
    )


def run_stored_ai_task(task, *, password: str = '') -> dict[str, Any]:
    """MailAiTask kaydını işler."""
    from webmail.models import MailAiTask

    account = task.account
    ctx = dict(task.context or {})
    ctx.setdefault('account_email', account.email)

    if task.task_type == MailAiTask.TYPE_ANALYZE:
        return ai_analyze_message(
            account,
            subject=ctx.get('subject', ''),
            from_addr=ctx.get('from', ''),
            body_text=ctx.get('body', ''),
        )

    chat_out = ai_chat(account, task.instruction, context=ctx)
    if not chat_out.get('success'):
        return chat_out

    action = chat_out.get('action') or {}
    intent = (action.get('intent') or 'chat').lower()
    if intent in ('send_mail', 'schedule_mail', 'reply') and password:
        exec_out = execute_ai_action(account, password, action)
        chat_out['executed'] = exec_out
        if exec_out.get('success'):
            chat_out['message'] = exec_out.get('message') or 'İşlem tamamlandı.'
        else:
            chat_out['success'] = False
            chat_out['message'] = exec_out.get('message') or 'İşlem başarısız.'
    return chat_out


def _strip_json_block(text: str) -> str:
    return sanitize_ai_text(re.sub(r'```json\s*[\s\S]*?```', '', text, flags=re.I))


def _parse_action_json(text: str) -> dict[str, Any]:
    m = re.search(r'```json\s*(\{[\s\S]*?\})\s*```', text, re.I)
    if not m:
        return {'intent': 'chat'}
    try:
        data = json.loads(m.group(1))
        intent = (data.get('intent') or 'chat').lower()
        send_at = data.get('send_at') or ''
        if intent == 'schedule_mail' and send_at:
            try:
                data['send_at_parsed'] = datetime.fromisoformat(send_at.replace('Z', '+00:00'))
            except Exception:
                data['send_at_parsed'] = timezone.now() + timedelta(hours=1)
        return data
    except json.JSONDecodeError:
        return {'intent': 'chat'}


def ai_compose_assist(account, *, instruction: str, tone: str = 'professional') -> dict[str, Any]:
    cfg = resolve_ai_config(account)
    if not cfg:
        return {'success': False, 'message': 'AI kullanılamıyor.'}
    prompt = f"Şu talimata göre e-posta gövdesi yaz ({tone} ton): {instruction}"
    try:
        out = chat_completion(
            api_key=cfg['api_key'],
            model=cfg['model'],
            messages=[
                {'role': 'system', 'content': cfg['system_prompt']},
                {'role': 'user', 'content': prompt},
            ],
            provider=cfg['provider'],
        )
    except ValueError as exc:
        return {'success': False, 'message': str(exc)}
    return {'success': True, 'body': out['content']}
