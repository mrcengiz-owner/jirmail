"""OpenRouter / OpenAI uyumlu chat tamamlama."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

OPENROUTER_URL = 'https://openrouter.ai/api/v1/chat/completions'

_SAFETY_LINE = re.compile(
    r'^(user\s+)?safety\s*:\s*(safe|unsafe|moderate|blocked).*$',
    re.I,
)
_META_LINE = re.compile(
    r'^(moderation|content.?filter|classification)\s*:\s*.+$',
    re.I,
)


def _extract_message_content(message: dict) -> str:
    """OpenAI/OpenRouter yanıtından düz metin çıkar."""
    content = message.get('content') or ''
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get('type') == 'text':
                    parts.append(str(part.get('text') or ''))
                elif 'text' in part:
                    parts.append(str(part.get('text') or ''))
            elif isinstance(part, str):
                parts.append(part)
        content = '\n'.join(p for p in parts if p)
    return str(content).strip()


def sanitize_ai_text(text: str) -> str:
    """Moderasyon etiketleri ve boş satırları temizle."""
    if not text:
        return ''
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _SAFETY_LINE.match(stripped):
            continue
        if _META_LINE.match(stripped):
            continue
        lines.append(line)
    return '\n'.join(lines).strip()


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
    message = choices[0].get('message') or {}
    content = sanitize_ai_text(_extract_message_content(message))
    return {'content': content, 'model': model, 'raw': data}
