"""Hesap + domain AI ayarları ve sohbet / komut işleme."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone

from webmail.ai.client import chat_completion


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


def ai_chat(account, user_message: str, *, context: dict | None = None) -> dict[str, Any]:
    cfg = resolve_ai_config(account)
    if not cfg:
        return {
            'success': False,
            'message': 'AI bu hesap için kapalı veya API anahtarı yok (domain ayarlarını kontrol edin).',
        }

    ctx = context or {}
    system = cfg['system_prompt'] + (
        '\n\nYanıtını JSON bloğu ile bitir: ```json\n'
        '{"intent":"chat|send_mail|schedule_mail|reply","to":"","subject":"","body":"","send_at":""}\n```\n'
        'send_mail/schedule_mail ise alanları doldur; chat ise intent=chat.'
    )
    if ctx.get('selected_subject'):
        system += f"\nSeçili mail konusu: {ctx['selected_subject']}"

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
