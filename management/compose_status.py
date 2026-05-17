"""Compose modunda Docker API olmadan servis durumu (TCP probe)."""
from __future__ import annotations

import os
import socket
from typing import Any

from django.conf import settings

from installer.compose_mode import is_compose_stack


def _tcp_ok(host: str, port: int, timeout: float = 2.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def compose_stack_containers() -> list[dict[str, Any]] | None:
    """JIR_COMPOSE_STACK=1 iken jir_* servislerinin TCP durumu."""
    if not is_compose_stack():
        return None

    smtp_host = os.getenv('SMTP_HOST', 'postfix')
    imap_host = os.getenv('IMAP_HOST', 'dovecot')
    smtp_port = int(getattr(settings, 'SMTP_PORT', 587))
    imap_port = int(getattr(settings, 'IMAP_PORT', 993))

    specs = [
        ('jir_postgres', 'postgres', 5432),
        ('jir_redis', 'redis', 6379),
        ('jir_postfix', smtp_host, smtp_port),
        ('jir_dovecot', imap_host, imap_port),
        ('jir_django', 'django', 8000),
    ]

    out: list[dict[str, Any]] = []
    for container_name, host, port in specs:
        running = _tcp_ok(host, port)
        out.append({
            'container_id': f'compose-{host}',
            'container_name': container_name,
            'status': 'running' if running else 'stopped',
            'cpu_percent': 0.0,
            'ram_percent': 0.0,
            'ram_usage_mb': 0.0,
            'ram_limit_mb': 0.0,
            'compose_managed': True,
            'probe_host': host,
            'probe_port': port,
            'error': (
                None
                if running
                else f'{host}:{port} erişilemiyor. Dokploy/docker compose üzerinden servisi kontrol edin.'
            ),
        })
    return out


def docker_api_available() -> bool:
    if is_compose_stack():
        return False
    try:
        import docker

        dh = getattr(settings, 'DOCKER_HOST', 'unix:///var/run/docker.sock')
        client = docker.DockerClient(base_url=dh, timeout=3)
        try:
            client.ping()
            return True
        finally:
            client.close()
    except Exception:
        return False
