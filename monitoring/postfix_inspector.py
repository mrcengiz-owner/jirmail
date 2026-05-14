"""Postfix mail queue inspector.

Docker SDK ile Postfix container'ı içinde `postqueue`, `postcat`, `postsuper`
komutlarını çalıştırarak kuyruğu yönetir.
"""
from __future__ import annotations

import re
import shlex
from typing import Iterable

from django.conf import settings


POSTFIX_CONTAINER = 'jir_postfix'


def _exec(cmd: list[str]) -> tuple[int, str]:
    """Postfix container'ında shell komutu çalıştır."""
    try:
        import docker
        docker_host = getattr(settings, 'DOCKER_HOST', 'unix://var/run/docker.sock')
        client = docker.DockerClient(base_url=docker_host, timeout=30)
        try:
            container = client.containers.get(POSTFIX_CONTAINER)
            exec_result = container.exec_run(cmd, demux=False)
            output = exec_result.output.decode('utf-8', errors='replace') if exec_result.output else ''
            return exec_result.exit_code or 0, output
        finally:
            client.close()
    except Exception as exc:
        return 1, str(exc)


_QUEUE_LINE_RE = re.compile(
    r'^(?P<id>[A-F0-9]+)\s+'
    r'(?P<size>\d+)\s+'
    r'(?P<date>\w{3}\s+\w{3}\s+\d{1,2}\s+\d{1,2}:\d{2}:\d{2})\s+'
    r'(?P<sender>\S+)'
)


def list_queue() -> list[dict]:
    """`postqueue -p` çıktısını parse ederek kuyruğu döndürür."""
    code, output = _exec(['postqueue', '-p'])
    if code != 0:
        return []

    entries: list[dict] = []
    current: dict | None = None

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('-Queue ID-') or stripped.startswith('--'):
            continue

        match = _QUEUE_LINE_RE.match(stripped)
        if match:
            if current:
                entries.append(current)
            current = {
                'id': match.group('id').rstrip('!*'),
                'size': int(match.group('size')),
                'date': match.group('date'),
                'sender': match.group('sender'),
                'recipients': [],
                'reason': '',
                'on_hold': stripped.startswith(match.group('id') + '!'),
                'deferred': '!' in match.group('id') or '*' in match.group('id'),
            }
        elif current:
            if '@' in stripped and not stripped.startswith('('):
                current['recipients'].append(stripped)
            elif stripped.startswith('('):
                current['reason'] = stripped.strip('()')

    if current:
        entries.append(current)
    return entries


def get_queue_count() -> int:
    code, output = _exec(['mailq'])
    if code != 0:
        return 0
    return sum(1 for line in output.splitlines() if _QUEUE_LINE_RE.match(line.strip()))


def flush_queue() -> dict:
    """Kuyrukta bekleyen tüm mailleri yeniden teslim etmeye çalış."""
    code, output = _exec(['postqueue', '-f'])
    return {'success': code == 0, 'output': output[:2000]}


def delete_message(queue_id: str) -> dict:
    """Belirli queue ID'sini sil."""
    code, output = _exec(['postsuper', '-d', queue_id])
    return {'success': code == 0, 'output': output[:2000]}


def delete_all() -> dict:
    code, output = _exec(['postsuper', '-d', 'ALL'])
    return {'success': code == 0, 'output': output[:2000]}


def view_message(queue_id: str) -> dict:
    """Tek bir mailin içeriğini incele (postcat)."""
    code, output = _exec(['postcat', '-q', queue_id])
    return {'success': code == 0, 'content': output[:20000]}


def hold_message(queue_id: str) -> dict:
    code, output = _exec(['postsuper', '-h', queue_id])
    return {'success': code == 0, 'output': output[:2000]}


def release_message(queue_id: str) -> dict:
    code, output = _exec(['postsuper', '-H', queue_id])
    return {'success': code == 0, 'output': output[:2000]}
