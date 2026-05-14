"""Mail log SSE streamer.

Docker SDK ile Postfix container'ından `tail -F /var/log/mail.log` çalıştırır
ve gelen satırları SSE üzerinden istemciye iletir.
"""
from __future__ import annotations

import json
import time
from typing import Iterator

from django.conf import settings
from django.http import StreamingHttpResponse


def _docker_client():
    import docker
    return docker.DockerClient(base_url=getattr(settings, 'DOCKER_HOST', 'unix://var/run/docker.sock'), timeout=600)


def tail_container_logs(container_name: str, lines: int = 100) -> Iterator[bytes]:
    """Container loglarını canlı yayınla."""
    yield b': stream open\n\n'

    try:
        client = _docker_client()
        container = client.containers.get(container_name)
        stream = container.logs(stream=True, follow=True, tail=lines, timestamps=True)
    except Exception as exc:
        msg = json.dumps({'error': str(exc)})
        yield f'event: error\ndata: {msg}\n\n'.encode('utf-8')
        return

    last_heartbeat = time.time()
    try:
        for chunk in stream:
            if not chunk:
                continue
            text = chunk.decode('utf-8', errors='replace').rstrip('\n')
            payload = json.dumps({'line': text, 'container': container_name})
            yield f'data: {payload}\n\n'.encode('utf-8')

            if time.time() - last_heartbeat > 15:
                yield b': heartbeat\n\n'
                last_heartbeat = time.time()
    except Exception as exc:
        msg = json.dumps({'error': str(exc)})
        yield f'event: error\ndata: {msg}\n\n'.encode('utf-8')
    finally:
        try:
            client.close()
        except Exception:
            pass


def log_sse_response(container_name: str = 'jir_postfix', lines: int = 100) -> StreamingHttpResponse:
    response = StreamingHttpResponse(
        tail_container_logs(container_name, lines=lines),
        content_type='text/event-stream',
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    return response
