"""OpenRouter / OpenAI uyumlu chat tamamlama."""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'


def chat_completion(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    provider: str = 'openrouter',
    timeout: float = 90.0,
) -> dict[str, Any]:
    if not api_key:
        raise ValueError('AI API anahtarı tanımlı değil')

    model = model or 'openai/gpt-4o-mini'
    url = OPENROUTER_URL
    if provider == 'openai':
        url = 'https://api.openai.com/v1/chat/completions'

    body = json.dumps({
        'model': model,
        'messages': messages,
        'temperature': 0.4,
    }).encode('utf-8')

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://jir-mail.local',
            'X-Title': 'Jir-Mail Webmail',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace')[:500]
        logger.warning('AI HTTP %s: %s', exc.code, detail)
        raise ValueError(f'AI sağlayıcı hatası ({exc.code}): {detail}') from exc

    choices = data.get('choices') or []
    if not choices:
        raise ValueError('AI yanıtı boş')
    content = (choices[0].get('message') or {}).get('content') or ''
    return {'content': content.strip(), 'model': model, 'raw': data}
