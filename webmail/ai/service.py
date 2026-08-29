"""Hesap + domain AI ayarları ve sohbet / komut işleme."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from webmail.ai.client import chat_completion

_AGENT_SYSTEM_SUFFIX = (
    '\n\nSen Jîr-Mail posta ajanısın. Gelen/giden postayı analiz eder, sınıflandırır, '
    'organize eder, taslak yazar, gönderim/planlama önerirsin. Türkçe yanıt ver.\n'
    'Yanıtını JSON bloğu ile bitir:\n'
    '```json\n'
    '{"intent":"chat|send_mail|schedule_mail|reply|analyze|archive|spam|move|'
    'mark_read|organize_inbox|run_agent|create_rule",'
    '"to":"","subject":"","body":"","send_at":"","summary":"",'
    '"uid":0,"folder":"INBOX","rule_name":"","match_from":"","match_subject":"",'
    '"action_type":"archive"}\n'
    '```\n'
    'organize_inbox/run_agent: posta düzenleme; create_rule: kalıcı kural öner.'
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
    return '\n'.join(parts)


def ai_chat(account, user_message: str, *, context: dict | None = None) -> dict[str, Any]:
    cfg = resolve_ai_config(account)
    if not cfg:
        return {
            'success': False,
            'message': 'AI bu hesap için kapalı veya API anahtarı yok (domain ayarlarını kontrol edin).',
        }

    ctx = dict(context or {})
    ctx.setdefault('account_email', getattr(account, 'email', ''))
    system = cfg['system_prompt'] + _AGENT_SYSTEM_SUFFIX
    ctx_block = _build_context_block(ctx)
    if ctx_block:
        system += '\n\n--- Bağlam ---\n' + ctx_block

    messages = [
        {'role': 'system', 'content': system},
        {'role': 'user', 'content': user_message},
    ]
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
    action = _parse_action_json(content)
    return {
        'success': True,
        'reply': _strip_json_block(content),
        'action': action,
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
        return execute_imap_action(
            account,
            password,
            folder=folder,
            uid=uid,
            action_type=act_map.get(intent, intent),
            action_target=action.get('move_to') or action.get('action_target') or '',
        )

    if intent == 'organize_inbox':
        from webmail.ai.agent import organize_inbox

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        return organize_inbox(account, password, autopilot=False)

    if intent == 'run_agent':
        from webmail.ai.agent import run_agent_cycle

        if not password:
            return {'success': False, 'message': 'Oturum parolası yok.'}
        return run_agent_cycle(account, password, triage=True, organize=True, digest=False)

    if intent == 'create_rule':
        from webmail.models import MailAiRule

        name = (action.get('rule_name') or action.get('name') or 'AI kuralı')[:120]
        row = MailAiRule.objects.create(
            account=account,
            name=name,
            match_from=(action.get('match_from') or '')[:255],
            match_subject=(action.get('match_subject') or '')[:255],
            match_category=(action.get('match_category') or '')[:32],
            action_type=(action.get('action_type') or MailAiRule.ACTION_ARCHIVE)[:32],
            action_target=(action.get('action_target') or action.get('move_to') or '')[:255],
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
    return re.sub(r'```json\s*[\s\S]*?```', '', text, flags=re.I).strip()


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
