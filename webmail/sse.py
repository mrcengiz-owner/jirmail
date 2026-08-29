"""Webmail için SSE — yeni mail push'u."""
from __future__ import annotations

import json
import time
from typing import Iterator

import redis
from django.conf import settings
from django.http import StreamingHttpResponse


def _redis():
    return redis.Redis.from_url(getattr(settings, 'CELERY_BROKER_URL', 'redis://127.0.0.1:6379/0'),
                                decode_responses=True)


def _channel(account_id: int) -> str:
    return f'webmail:account:{account_id}'


def _publish(account_id: int, event: dict) -> None:
    try:
        _redis().publish(_channel(account_id), json.dumps(event))
    except Exception:
        pass


def publish_new_mail(account_id: int, payload: dict) -> None:
    _publish(account_id, {'type': 'new_mail', 'payload': payload})


def publish_outbound_status(
    account_id: int,
    outbound_id: int,
    status: str,
    message: str = '',
) -> None:
    _publish(account_id, {
        'type': 'outbound_status',
        'payload': {
            'outbound_id': outbound_id,
            'status': status,
            'message': message,
        },
    })


def publish_ai_task_status(account_id: int, task_id: int, status: str, result: dict | None = None) -> None:
    _publish(account_id, {
        'type': 'ai_task_status',
        'payload': {
            'task_id': task_id,
            'status': status,
            'result': result or {},
        },
    })


def publish_agent_event(account_id: int, event_type: str, payload: dict | None = None) -> None:
    _publish(account_id, {
        'type': event_type,
        'payload': payload or {},
    })


def publish_approval_update(account_id: int, event: str, payload: dict | None = None) -> None:
    _publish(account_id, {
        'type': 'approval_update',
        'payload': {'event': event, **(payload or {})},
    })


def webmail_event_stream(account_id: int) -> Iterator[bytes]:
    yield b': open\n\n'
    try:
        pubsub = _redis().pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(_channel(account_id))
    except Exception as exc:
        yield f'event: error\ndata: {json.dumps({"message": str(exc)})}\n\n'.encode('utf-8')
        return

    last = time.time()
    try:
        while True:
            msg = pubsub.get_message(timeout=1.0)
            if msg and msg.get('type') == 'message':
                yield f'data: {msg["data"]}\n\n'.encode('utf-8')
            if time.time() - last > 15:
                yield b': heartbeat\n\n'
                last = time.time()
    finally:
        try:
            pubsub.close()
        except Exception:
            pass


def webmail_sse_response(account_id: int) -> StreamingHttpResponse:
    response = StreamingHttpResponse(webmail_event_stream(account_id), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
