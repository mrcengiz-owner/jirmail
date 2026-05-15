"""Kurulum öncesi host port uygunluğu (Docker publish çakışmaları)."""
from __future__ import annotations

import socket
from typing import Any


def host_port_available(port: int, host: str = '0.0.0.0') -> bool:
    """Port host üzerinde bind edilebiliyorsa True (boş). Docker genelde 0.0.0.0 publish eder."""
    if port < 1 or port > 65535:
        return False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
        return True
    except OSError:
        return False


def scan_mail_stack_ports() -> dict[str, Any]:
    """Kurulum öncesi UI için 25/587/993/143 durumu."""
    labels = {25: 'SMTP (25)', 587: 'Submission (587)', 993: 'IMAPS (993)', 143: 'IMAP (143)'}
    busy: list[dict[str, Any]] = []
    free: list[int] = []
    for port in (25, 587, 993, 143):
        if host_port_available(port):
            free.append(port)
        else:
            busy.append({'port': port, 'label': labels.get(port, str(port))})
    return {'busy': busy, 'free': free, 'all_mail_ports_free': len(busy) == 0}


def filter_publish_ports(
    ports: dict[str, Any] | None,
    *,
    skip_busy: bool = True,
) -> tuple[dict[str, Any], list[int]]:
    """Docker ports sözlüğünden dolu host portlarını çıkarır.

    ports örneği: {'25/tcp': 25, '587/tcp': 587}
    Dönüş: (filtrelenmiş dict, atlanan host port listesi)
    """
    if not ports:
        return {}, []

    filtered: dict[str, Any] = {}
    skipped: list[int] = []

    for container_spec, host_port in ports.items():
        try:
            hp = int(host_port)
        except (TypeError, ValueError):
            filtered[container_spec] = host_port
            continue

        if host_port_available(hp):
            filtered[container_spec] = host_port
        elif skip_busy:
            skipped.append(hp)
        else:
            raise RuntimeError(
                f'Host portu {hp} kullanımda ({container_spec}). '
                f'Mevcut servisi durdurun (ör. sistem postfix: sudo systemctl stop postfix) '
                f'veya kurulumda "dolu portları atla" seçeneğini kullanın.'
            )

    return filtered, skipped
