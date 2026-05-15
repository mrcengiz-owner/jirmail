"""Host'ta runserver iken Postfix/Dovecot'a erişim (publish yoksa Docker köprü IP)."""
from __future__ import annotations

import logging
import os
import socket
from typing import Any

from django.conf import settings

from .docker_containers import merged_container_name

logger = logging.getLogger(__name__)

JIR_NETWORK = 'jir_network'

_SERVICE_HINTS: dict[str, tuple[str, ...]] = {
    'postfix': ('postfix', 'smtp', 'boky/postfix', 'mta'),
    'dovecot': ('dovecot', 'imap', 'pop3'),
}


def tcp_reachable(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _docker_client():
    import docker

    dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
    return docker.DockerClient(base_url=dh, timeout=8)


def _container_ip_on_network(container, network: str = JIR_NETWORK) -> str | None:
    nets = (container.attrs.get('NetworkSettings') or {}).get('Networks') or {}
    if not isinstance(nets, dict):
        return None
    if network in nets:
        ip = (nets[network] or {}).get('IPAddress')
        if ip:
            return str(ip)
    for data in nets.values():
        if isinstance(data, dict):
            ip = data.get('IPAddress')
            if ip:
                return str(ip)
    return None


def _find_service_container(client, service_key: str):
    """merged_container_map / isim / imaj ipucu ile konteyner bul."""
    import docker

    sk = service_key.strip().lower()
    primary = merged_container_name(sk)
    if primary:
        try:
            return client.containers.get(primary)
        except docker.errors.NotFound:
            pass
        except Exception:
            pass

    hints = _SERVICE_HINTS.get(sk, ())
    best = None
    for c in client.containers.list(all=True):
        nm = (c.name or '').lower()
        img = ''
        try:
            img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
        except Exception:
            pass
        if any(h in nm or h in img for h in hints):
            if getattr(c, 'status', None) == 'running':
                return c
            if best is None:
                best = c
    return best


def _env_host_port(service_key: str, default_port: int) -> tuple[str, int] | None:
    sk = service_key.strip().lower()
    if sk == 'postfix':
        host = (os.getenv('SMTP_HOST') or os.getenv('POSTFIX_SMTP_HOST') or '').strip()
        port_raw = os.getenv('SMTP_PORT', '')
    elif sk == 'dovecot':
        host = (os.getenv('IMAP_HOST') or os.getenv('DOVECOT_IMAP_HOST') or '').strip()
        port_raw = os.getenv('IMAP_PORT', '')
    else:
        return None
    if not host:
        return None
    try:
        port = int(port_raw) if str(port_raw).strip() else default_port
    except ValueError:
        port = default_port
    return host, port


def resolve_mail_endpoint(service_key: str, default_port: int) -> tuple[str, int]:
    """Mail servisi (host, port): env → Docker DNS adı → localhost → köprü IP."""
    sk = service_key.strip().lower()
    env_hp = _env_host_port(sk, default_port)
    if env_hp:
        return env_hp

    if getattr(settings, 'IN_DOCKER', False):
        name = merged_container_name(sk) or f'jir_{sk}'
        return name, default_port

    ports_to_try = [default_port]
    if sk == 'postfix' and default_port not in (25,):
        ports_to_try.append(25)
    elif sk == 'postfix' and default_port == 587:
        ports_to_try = [587, 25]

    for port in ports_to_try:
        if tcp_reachable('127.0.0.1', port):
            return '127.0.0.1', port

    client = None
    try:
        client = _docker_client()
        client.ping()
        container = _find_service_container(client, sk)
        if container:
            container.reload()
            ip = _container_ip_on_network(container)
            if ip:
                for port in ports_to_try:
                    if tcp_reachable(ip, port):
                        logger.info(
                            'Mail %s: köprü IP %s:%s (%s)',
                            sk, ip, port, container.name,
                        )
                        return ip, port
    except Exception as exc:
        logger.warning('Docker üzerinden %s endpoint çözülemedi: %s', sk, exc)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass

    return '127.0.0.1', default_port
