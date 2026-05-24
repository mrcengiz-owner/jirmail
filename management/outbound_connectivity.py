"""Dış posta çıkışı — port 25 ve relayhost tanılama."""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)

# Bilinen MX sunucuları (doğrudan SMTP teslimat testi).
# Google için yalnızca gmail-smtp-in kullanılır; aspmx.l.google.com sık zaman aşımı verir.
OUTBOUND_PROBE_TARGETS: tuple[tuple[str, int, str], ...] = (
    ('gmail-smtp-in.l.google.com', 25, 'Gmail MX'),
    ('mail.protonmail.ch', 25, 'Proton MX'),
    ('hotmail-com.olc.protection.outlook.com', 25, 'Outlook MX'),
)

PROBE_TIMEOUT_SEC = 8.0
PROBE_RETRIES = 1


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
    shell = (
        f'timeout {int(PROBE_TIMEOUT_SEC)} bash -c '
        f'"exec 3<>/dev/tcp/{host}/{int(port)}" 2>/dev/null '
        f'&& echo OK || echo FAIL'
    )
    last_err = ''
    for attempt in range(PROBE_RETRIES + 1):
        try:
            client = _docker_client()
            c = client.containers.get(name)
            code, logs = c.exec_run(['bash', '-c', shell], demux=True)
            stdout = ((logs[0] or b'') + (logs[1] or b'')).decode().strip()
            client.close()
            if 'OK' in stdout:
                suffix = f' (deneme {attempt + 1})' if attempt else ''
                return True, f'Postfix konteynerinden TCP OK{suffix}', name
            last_err = stdout or f'exit {code}'
        except Exception as exc:
            last_err = str(exc)
    return False, f'Postfix konteynerinden erişilemedi: {last_err}', name


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
    postfix_ok_count = sum(1 for p in probes if p['from_postfix'])
    postfix_total = len(probes)

    ok = any_postfix
    recommendation = ''
    if not ok:
        recommendation = (
            'Sunucudan (Postfix konteyneri) internet MX port 25\'e çıkış yok. '
            'Deploy ve gönderim sırasında sistem otomatik relay uygular. '
            'Kalıcı çözüm: .env → SMTP_RELAYHOST=[relay]:587 veya '
            'SMTP_RELAY_HOST/PORT/USER/PASSWORD. Ardından stack yeniden başlatılır.'
        )
    elif postfix_ok_count < postfix_total:
        recommendation = (
            f'Postfix port 25 çıkışı çalışıyor ({postfix_ok_count}/{postfix_total} hedef OK). '
            'Tekil MX zaman aşımı gönderimi engellemez; Gmail/Proton gibi en az bir hedef yeterlidir.'
        )
    elif not any_panel and include_django_probe:
        recommendation = (
            'Postfix çıkışı çalışıyor; panel konteynerinden 25 kapalı olabilir (normal). '
            'Gönderim Postfix üzerinden yapılır.'
        )

    if ok and postfix_ok_count < postfix_total:
        message = (
            f'Port 25 doğrudan çıkış: OK ({postfix_ok_count}/{postfix_total} MX hedefi; '
            'kısmi zaman aşımı normal)'
        )
    elif ok:
        message = 'Port 25 doğrudan çıkış: OK'
    else:
        message = 'Port 25 doğrudan çıkış: BAŞARISIZ — SMTP_RELAYHOST gerekli'

    return {
        'ok': ok,
        'mode': 'direct',
        'relayhost': '',
        'env_relayhost': env_relay,
        'port25_required': True,
        'message': message,
        'probes': probes,
        'probe_summary': {'postfix_ok': postfix_ok_count, 'postfix_total': postfix_total},
        'recommendation': recommendation,
    }
