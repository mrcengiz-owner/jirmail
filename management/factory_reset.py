"""Fabrika sıfırlama — veritabanı, kurulum bayrakları ve (isteğe bağlı) Docker stack."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

CONFIRM_PHRASE = 'SIFIRDAN KUR'

# docker-compose.yml named volumes
STACK_VOLUME_NAMES: tuple[str, ...] = (
    'jir_postgres_data',
    'jir_redis_data',
    'jir_postfix_data',
    'jir_mail_data',
    'jir_mail_tls',
    'jir_config_data',
)

CONFIG_DIR = Path(getattr(settings, 'BASE_DIR', Path('/app'))) / 'config'
INSTALLED_FLAG = CONFIG_DIR / '.installed'
DB_CONFIG_JSON = CONFIG_DIR / 'db_config.json'
OUTBOUND_STATE = CONFIG_DIR / 'outbound_delivery.json'


def _docker_client():
    import docker

    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=30)


def _stack_container_names() -> list[str]:
    from management.docker_containers import SERVICE_KEYS, merged_container_name

    names: list[str] = []
    for sk in SERVICE_KEYS:
        n = merged_container_name(sk)
        if n and n not in names:
            names.append(n)
    return names


def clear_install_artifacts() -> list[str]:
    """Kurulum bayrakları ve önbellek dosyaları."""
    removed: list[str] = []
    for path in (INSTALLED_FLAG, DB_CONFIG_JSON, OUTBOUND_STATE):
        try:
            if path.is_file():
                path.unlink()
                removed.append(str(path))
        except Exception as exc:
            logger.warning('factory_reset unlink %s: %s', path, exc)
    return removed


def reset_database() -> dict[str, Any]:
    """Tüm Django tablolarını boşalt (migrate yapısı kalır)."""
    from django.core.management import call_command

    try:
        call_command('flush', '--noinput', verbosity=0)
        return {'ok': True, 'message': 'Veritabanı sıfırlandı (flush)'}
    except Exception as exc:
        logger.exception('factory_reset flush')
        return {'ok': False, 'message': str(exc)}


def tear_down_stack(*, remove_volumes: bool = True) -> dict[str, Any]:
    """Stack konteynerlerini durdur/sil; isteğe bağlı named volume sil."""
    import docker

    report: dict[str, Any] = {'containers': [], 'volumes': [], 'ok': True}
    client = None
    try:
        client = _docker_client()
        client.ping()
    except Exception as exc:
        return {'ok': False, 'error': f'Docker erişilemiyor: {exc}', 'containers': [], 'volumes': []}

    try:
        # Önce worker/mail, django en sonda
        order = _stack_container_names()
        if order:
            django_name = None
            try:
                from management.docker_containers import merged_container_name

                django_name = merged_container_name('django')
            except Exception:
                pass
            if django_name in order:
                order = [n for n in order if n != django_name] + [django_name]

        for name in order:
            entry = {'name': name, 'ok': False}
            try:
                c = client.containers.get(name)
                c.stop(timeout=15)
                c.remove(force=True)
                entry['ok'] = True
                entry['action'] = 'removed'
            except docker.errors.NotFound:
                entry['action'] = 'not_found'
                entry['ok'] = True
            except Exception as exc:
                entry['action'] = 'error'
                entry['message'] = str(exc)
                report['ok'] = False
            report['containers'].append(entry)

        if remove_volumes:
            for vol_name in STACK_VOLUME_NAMES:
                vent = {'name': vol_name, 'ok': False}
                try:
                    v = client.volumes.get(vol_name)
                    v.remove(force=True)
                    vent['ok'] = True
                    vent['action'] = 'removed'
                except docker.errors.NotFound:
                    vent['ok'] = True
                    vent['action'] = 'not_found'
                except Exception as exc:
                    vent['action'] = 'error'
                    vent['message'] = str(exc)
                    report['ok'] = False
                report['volumes'].append(vent)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
    return report


def _schedule_stack_teardown(*, remove_volumes: bool, delay_sec: float = 4.0) -> None:
    """HTTP yanıtı döndükten sonra stack'i sök (django konteyneri dahil)."""

    def _run() -> None:
        time.sleep(delay_sec)
        try:
            tear_down_stack(remove_volumes=remove_volumes)
        except Exception as exc:
            logger.exception('factory_reset async teardown: %s', exc)

    threading.Thread(target=_run, name='jir-factory-reset-teardown', daemon=True).start()


def run_factory_reset(
    *,
    remove_volumes: bool = True,
    remove_containers: bool = True,
) -> dict[str, Any]:
    """Sıfırdan kurulum: DB flush + bayrak temizliği + (opsiyonel) stack sökümü."""
    from installer.compose_mode import is_compose_stack

    report: dict[str, Any] = {
        'ok': True,
        'database': {},
        'artifacts': [],
        'stack': {'scheduled': False},
        'redirect': '/setup/',
        'warnings': [],
    }

    report['artifacts'] = clear_install_artifacts()
    report['database'] = reset_database()
    if not report['database'].get('ok'):
        report['ok'] = False
        return report

    if remove_containers:
        if not is_compose_stack():
            report['warnings'].append(
                'Compose stack algılanmadı — konteynerler otomatik silinmedi. '
                'Elle docker compose down -v çalıştırın.'
            )
        else:
            try:
                _docker_client().ping()
                _schedule_stack_teardown(remove_volumes=remove_volumes)
                report['stack'] = {
                    'scheduled': True,
                    'remove_volumes': remove_volumes,
                    'message': (
                        'Konteynerler ve volume\'lar birkaç saniye içinde silinecek. '
                        'Dokploy/Coolify üzerinden projeyi yeniden deploy edin, ardından /setup/ açın.'
                    ),
                }
            except Exception as exc:
                report['warnings'].append(
                    f'Docker soketi yok ({exc}). Konteynerleri elle silin: '
                    'docker compose down -v --remove-orphans'
                )
                report['stack'] = {'scheduled': False, 'error': str(exc)}
    elif remove_volumes:
        report['warnings'].append('remove_containers=false — volume silme atlandı.')

    if report['stack'].get('scheduled'):
        report['warnings'].append(
            'Bu oturum birkaç saniye içinde kapanabilir. Deploy sonrası kurulum sihirbazına gidin.'
        )

    return report
