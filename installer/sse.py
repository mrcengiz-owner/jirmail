"""Server-Sent Events (SSE) yardımcı modülü.

Django WSGI üzerinden bile StreamingHttpResponse ile çalışan basit bir SSE
implementasyonu. Redis Pub/Sub üzerinden event'leri abone olur ve istemciye
text/event-stream akışı olarak gönderir.
"""
from __future__ import annotations

import json
import time
from typing import Iterator, Optional

import redis
from django.conf import settings
from django.http import StreamingHttpResponse


def _get_redis():
    """Redis client'ı oluştur. CELERY_BROKER_URL'i kullanır."""
    url = getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0')
    return redis.Redis.from_url(url, decode_responses=True)


def channel_for_run(run_id: str) -> str:
    return f'installer:run:{run_id}'


def publish_event(run_id: str, event_type: str, payload: dict) -> None:
    """Bir kurulum çalışmasına event gönder."""
    try:
        r = _get_redis()
        message = json.dumps({'type': event_type, 'payload': payload})
        r.publish(channel_for_run(run_id), message)
    except Exception:
        pass


def event_stream(run_id: str, *, last_event_id: Optional[str] = None) -> Iterator[bytes]:
    """SSE event'lerini üreten generator.

    Redis Pub/Sub'a abone olur ve heartbeat ile birlikte event'leri yields eder.
    """
    yield b': stream open\n\n'

    try:
        r = _get_redis()
        pubsub = r.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(channel_for_run(run_id))
    except Exception as exc:
        msg = json.dumps({'type': 'error', 'payload': {'message': str(exc)}})
        yield f'event: error\ndata: {msg}\n\n'.encode('utf-8')
        return

    last_heartbeat = time.time()
    try:
        while True:
            message = pubsub.get_message(timeout=1.0)
            if message and message.get('type') == 'message':
                data = message.get('data')
                if isinstance(data, str):
                    yield f'data: {data}\n\n'.encode('utf-8')
                    try:
                        parsed = json.loads(data)
                        if parsed.get('type') in ('completed', 'failed'):
                            break
                    except Exception:
                        pass
            if time.time() - last_heartbeat > 15:
                yield b': heartbeat\n\n'
                last_heartbeat = time.time()
    finally:
        try:
            pubsub.close()
        except Exception:
            pass


def sse_response(run_id: str) -> StreamingHttpResponse:
    """SSE endpoint'i için hazır StreamingHttpResponse oluştur.

    NOT: 'Connection: keep-alive' bilinçli olarak set edilmiyor — Django'nun
    wsgiref dev server'ı hop-by-hop header'lara izin vermiyor. Production'da
    bu davranışı reverse proxy (nginx/caddy) zaten halleder.
    """
    response = StreamingHttpResponse(event_stream(run_id), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
