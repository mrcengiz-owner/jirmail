"""Dış posta çıkışı — port 25 ve relayhost tanılama."""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# Bilinen MX sunucuları (doğrudan SMTP teslimat testi)
OUTBOUND_PROBE_TARGETS: tuple[tuple[str, int, str], ...] = (
    ('gmail-smtp-in.l.google.com', 25, 'Gmail MX'),
    ('mail.protonmail.ch', 25, 'Proton MX'),
    ('aspmx.l.google.com', 25, 'Google ASPMX'),
)

PROBE_TIMEOUT_SEC = 6.0


def _postfix_container_name() -> str:
    return (os.getenv('JIR_CONTAINER_POSTFIX') or 'jir_postfix').strip()


def _docker_client():
    import docker

    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=15)


def tcp_probe(host: str, port: int, *, timeout: float = PROBE_TIMEOUT_SEC) -> tuple[bool, str]:
    """Bu süreçten TCP bağlantısı (Django konteyneri veya host)."""
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, 'TCP bağlantısı başarılı'
    except socket.timeout:
        return False, 'Zaman aşımı (port kapalı veya filtrelenmiş olabilir)'
    except ConnectionRefusedError:
        return False, 'Bağlantı reddedildi'
    except OSError as exc:
        return False, str(exc)


def tcp_probe_from_postfix(host: str, port: int, *, container: str | None = None) -> tuple[bool, str, str]:
    """Postfix konteynerinden çıkış testi (gerçek gönderim yolu)."""
    name = container or _postfix_container_name()
    # bash /dev/tcp — boky/postfix imajında genelde mevcut
    shell = (
        f'timeout {int(PROBE_TIMEOUT_SEC)} bash -c '
        f'"exec 3<>/dev/tcp/{host}/{int(port)}" 2>/dev/null '
        f'&& echo OK || echo FAIL'
    )
    try:
        client = _docker_client()
        c = client.containers.get(name)
        code, logs = c.exec_run(['bash', '-c', shell], demux=True)
        stdout = ((logs[0] or b'') + (logs[1] or b'')).decode().strip()
        client.close()
        if 'OK' in stdout:
            return True, 'Postfix konteynerinden TCP OK', name
        err = stdout or f'exit {code}'
        return False, f'Postfix konteynerinden erişilemedi: {err}', name
    except Exception as exc:
        return False, f'Postfix exec hatası ({name}): {exc}', name


def get_postfix_relayhost(*, container: str | None = None) -> str:
    """postconf relayhost değeri."""
    name = container or _postfix_container_name()
    try:
        client = _docker_client()
        c = client.containers.get(name)
        code, logs = c.exec_run(['postconf', '-h', 'relayhost'], demux=True)
        stdout = (logs[0] or b'').decode().strip()
        client.close()
        if code == 0:
            return stdout
    except Exception as exc:
        logger.debug('relayhost okunamadı: %s', exc)
    return (getattr(settings, 'SMTP_RELAYHOST', '') or os.getenv('SMTP_RELAYHOST', '') or '').strip()


def check_outbound_smtp(*, include_django_probe: bool = True) -> dict[str, Any]:
    """Dış posta çıkışı raporu."""
    relayhost = get_postfix_relayhost()
    env_relay = (getattr(settings, 'SMTP_RELAYHOST', '') or '').strip()
    probes: list[dict[str, Any]] = []

    if relayhost:
        return {
            'ok': True,
            'mode': 'relay',
            'relayhost': relayhost,
            'env_relayhost': env_relay,
            'port25_required': False,
            'message': (
                f'Dış posta relayhost ile gidiyor ({relayhost}). '
                'Doğrudan port 25 çıkışı zorunlu değil.'
            ),
            'probes': probes,
            'recommendation': '',
        }

    for host, port, label in OUTBOUND_PROBE_TARGETS:
        pf_ok, pf_msg, pf_container = tcp_probe_from_postfix(host, port)
        entry: dict[str, Any] = {
            'target': label,
            'host': host,
            'port': port,
            'from_postfix': pf_ok,
            'postfix_message': pf_msg,
            'postfix_container': pf_container,
        }
        if include_django_probe:
            dj_ok, dj_msg = tcp_probe(host, port)
            entry['from_panel'] = dj_ok
            entry['panel_message'] = dj_msg
        probes.append(entry)

    any_postfix = any(p['from_postfix'] for p in probes)
    any_panel = any(p.get('from_panel') for p in probes) if include_django_probe else False

    ok = any_postfix
    recommendation = ''
    if not ok:
        recommendation = (
            'Sunucudan (Postfix konteyneri) internet MX port 25\'e çıkış yok. '
            'Bu VPS/hosting sağlayıcılarında yaygındır. Çözüm: .env dosyasına SMTP relay ekleyin, '
            'örnek: SMTP_RELAYHOST=[smtp.sendgrid.net]:587 veya ISP SMTP sunucunuz. '
            'Ardından: docker compose up -d postfix && docker exec jir_postfix '
            'sh /docker-init.d/30-jirmail-outbound-smtp.sh'
        )
    elif not any_panel and include_django_probe:
        recommendation = (
            'Postfix çıkışı çalışıyor; panel konteynerinden 25 kapalı olabilir (normal). '
            'Gönderim Postfix üzerinden yapılır.'
        )

    return {
        'ok': ok,
        'mode': 'direct',
        'relayhost': '',
        'env_relayhost': env_relay,
        'port25_required': True,
        'message': (
            'Port 25 doğrudan çıkış: OK'
            if ok
            else 'Port 25 doğrudan çıkış: BAŞARISIZ — SMTP_RELAYHOST gerekli'
        ),
        'probes': probes,
        'recommendation': recommendation,
    }
