"""Compose deploy sonrası tüm stack konteynerlerini yeniden başlat."""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

from django.conf import settings

from installer.compose_mode import is_compose_stack
from management.docker_containers import SERVICE_KEYS, merged_container_name

logger = logging.getLogger(__name__)

# Django kendini yeniden başlatmasın
_RESTART_ORDER = (
    'celery_beat',
    'celery',
    'postfix',
    'dovecot',
    'redis',
    'postgres',
)


def _docker_client(timeout: int = 15):
    import docker

    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=timeout)


def _self_container_id() -> str:
    return (os.environ.get('HOSTNAME') or socket.gethostname() or '').strip()


def _wait_database_ready(max_seconds: int = 90) -> None:
    import time

    for _ in range(max_seconds):
        try:
            from django.db import connection

            connection.close()
            connection.ensure_connection()
            return
        except Exception:
            time.sleep(1)
    logger.warning('postgres restart sonrası DB hazır değil (%ss)', max_seconds)


def restart_service_container(client, service_key: str, *, timeout: int = 30) -> dict[str, Any]:
    import docker

    name = merged_container_name(service_key)
    if not name:
        return {'service': service_key, 'ok': False, 'message': 'Konteyner adı tanımsız'}

    self_id = _self_container_id()
    try:
        container = client.containers.get(name)
        if self_id and container.id.startswith(self_id[:12]):
            return {'service': service_key, 'ok': True, 'skipped': True, 'message': 'atlandı (django)'}
        container.restart(timeout=timeout)
        return {'service': service_key, 'ok': True, 'container': container.name, 'message': 'yeniden başlatıldı'}
    except docker.errors.NotFound:
        return {'service': service_key, 'ok': False, 'message': f'{name} bulunamadı'}
    except Exception as exc:
        logger.warning('restart %s: %s', service_key, exc)
        return {'service': service_key, 'ok': False, 'message': str(exc)}


def restart_compose_stack(*, include_postgres: bool = True) -> dict[str, Any]:
    """
    Deploy sonrası mail stack + worker konteynerlerini yeniden başlatır.
    Yalnızca JIR_COMPOSE_STACK ve docker.sock erişimi varken çalışır.
    """
    if not is_compose_stack():
        return {'ok': True, 'skipped': True, 'reason': 'compose_stack_değil'}

    if os.environ.get('JIR_SKIP_DEPLOY_RESTART', '').strip().lower() in ('1', 'true', 'yes'):
        return {'ok': True, 'skipped': True, 'reason': 'JIR_SKIP_DEPLOY_RESTART'}

    if os.environ.get('JIR_AUTO_RESTART_STACK_ON_DEPLOY', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return {'ok': True, 'skipped': True, 'reason': 'JIR_AUTO_RESTART_STACK_ON_DEPLOY=0'}

    client = None
    results: list[dict[str, Any]] = []
    try:
        client = _docker_client()
        client.ping()
        keys = list(_RESTART_ORDER)
        if not include_postgres:
            keys = [k for k in keys if k != 'postgres']

        for sk in keys:
            if sk not in SERVICE_KEYS:
                continue
            results.append(restart_service_container(client, sk))
            if sk == 'postgres':
                _wait_database_ready()

        ok = all(r.get('ok') for r in results)
        return {'ok': ok, 'restarted': results}
    except Exception as exc:
        logger.warning('compose stack restart: %s', exc)
        return {'ok': False, 'error': str(exc), 'restarted': results}
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
