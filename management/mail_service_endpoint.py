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


def _hostname_resolves(hostname: str) -> bool:
    h = (hostname or '').strip()
    if not h or h in ('127.0.0.1', 'localhost'):
        return True
    try:
        socket.getaddrinfo(h, None, type=socket.SOCK_STREAM)
        return True
    except socket.gaierror:
        return False


def _docker_host_candidates(service_key: str) -> list[str]:
    """Konteyner içi SMTP/IMAP için denenecek hostname sırası (tekrarsız)."""
    sk = service_key.strip().lower()
    seen: set[str] = set()
    out: list[str] = []

    def add(host: str | None) -> None:
        h = (host or '').strip()
        if not h or h in seen:
            return
        seen.add(h)
        out.append(h)

    add(merged_container_name(sk))
    if sk == 'postfix':
        for h in ('postfix', 'smtp', 'mail', 'mta'):
            add(h)
    elif sk == 'dovecot':
        for h in ('dovecot', 'imap'):
            add(h)
    add(f'jir_{sk}')

    client = None
    try:
        client = _docker_client()
        client.ping()
        container = _find_service_container(client, sk)
        if container:
            container.reload()
            attrs = container.attrs or {}
            add(container.name)
            labs = (attrs.get('Config') or {}).get('Labels') or {}
            if isinstance(labs, dict):
                add((labs.get('com.docker.compose.service') or '').strip())
            nets = ((attrs.get('NetworkSettings') or {}).get('Networks') or {})
            if isinstance(nets, dict):
                for net_data in nets.values():
                    if not isinstance(net_data, dict):
                        continue
                    for alias in net_data.get('Aliases') or []:
                        add(str(alias).strip())
    except Exception as exc:
        logger.debug('Docker host adayları toplanamadı (%s): %s', sk, exc)
    finally:
        if client:
            try:
                client.close()
            except Exception:
                pass
    return out


def _resolve_mail_endpoint_in_docker(
    service_key: str,
    default_port: int,
    *,
    auth_submission: bool = False,
) -> tuple[str, int]:
    """IN_DOCKER: çözülebilir DNS adı veya köprü IP; jir_* yalnızca DNS tutuyorsa."""
    sk = service_key.strip().lower()
    if sk == 'postfix' and auth_submission:
        ports_to_try = [default_port]
    else:
        ports_to_try = [default_port]
        if sk == 'postfix' and default_port not in (25,):
            ports_to_try.append(25)

    for host in _docker_host_candidates(sk):
        if not _hostname_resolves(host):
            continue
        for port in ports_to_try:
            if tcp_reachable(host, port):
                logger.info('Mail %s: %s:%s (DNS + TCP)', sk, host, port)
                return host, port

    for host in _docker_host_candidates(sk):
        if _hostname_resolves(host):
            logger.info('Mail %s: %s:%s (DNS, TCP doğrulanamadı)', sk, host, default_port)
            return host, default_port

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

    fallback = merged_container_name(sk) or f'jir_{sk}'
    logger.warning(
        'Mail %s: hiçbir aday çözülmedi/TCP yok; fallback %r — kurulum sihirbazı mail adımı '
        'veya SMTP_HOST/IMAP_HOST / JIR_CONTAINER_*.',
        sk,
        fallback,
    )
    return fallback, default_port


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


def _stored_mail_endpoint(service_key: str, default_port: int) -> tuple[str, int] | None:
    """Kurulum sihirbazının kaydettiği SMTP/IMAP (SystemConfig.installation_log)."""
    try:
        from installer.mail_connectivity import mail_endpoints_from_system_config

        ep = mail_endpoints_from_system_config()
        if not ep:
            return None
        sk = service_key.strip().lower()
        if sk == 'postfix':
            host = (ep.get('smtp_host') or '').strip()
            port = int(ep.get('smtp_port') or default_port)
        elif sk == 'dovecot':
            host = (ep.get('imap_host') or '').strip()
            port = int(ep.get('imap_port') or default_port)
        else:
            return None
        if host:
            return host, port
    except Exception:
        pass
    return None


def resolve_mail_endpoint(
    service_key: str,
    default_port: int,
    *,
    auth_submission: bool = False,
) -> tuple[str, int]:
    """Mail servisi (host, port): env → kurulum kaydı → Docker DNS → localhost → köprü IP.

    auth_submission=True (SMTP LOGIN gönderimi): yalnızca submission portu (örn. 587)
    denenir; 25'e düşülmez — çoğu kurulumda 25 AUTH sunmaz ve Python 3.12'de
    SMTPNotSupportedError üretir.
    """
    sk = service_key.strip().lower()
    env_hp = _env_host_port(sk, default_port)
    if env_hp:
        return env_hp

    stored = _stored_mail_endpoint(sk, default_port)
    if stored:
        return stored

    if getattr(settings, 'IN_DOCKER', False):
        return _resolve_mail_endpoint_in_docker(
            sk, default_port, auth_submission=auth_submission
        )

    if sk == 'postfix' and auth_submission:
        ports_to_try = [default_port]
    else:
        ports_to_try = [default_port]
        if sk == 'postfix' and default_port not in (25,):
            ports_to_try.append(25)

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
