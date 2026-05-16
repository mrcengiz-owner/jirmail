"""Postfix / Dovecot Docker keşfi — Coolify ve benzeri PaaS için tek kaynak çıktı."""
from __future__ import annotations

import os
from typing import Any

from django.conf import settings

from management.docker_containers import merged_container_name, read_stored_container_map
from management.mail_service_endpoint import resolve_mail_endpoint, tcp_reachable


def relevant_platform_env() -> dict[str, str]:
    """Coolify / dokploy vb. tanı için sık kullanılan ortam değişkenleri."""
    keys = (
        'COOLIFY_FQDN',
        'COOLIFY_RESOURCE_UUID',
        'COOLIFY_CONTAINER_NAME',
        'COOLIFY_APPLICATION_UUID',
        'DATABASE_URL',
        'DOCKER_HOST',
        'IN_DOCKER',
        'JIR_CONTAINER_POSTFIX',
        'JIR_CONTAINER_DOVECOT',
        'JIR_CONTAINER_POSTGRES',
        'JIR_CONTAINER_REDIS',
        'SMTP_HOST',
        'SMTP_PORT',
        'IMAP_HOST',
        'IMAP_PORT',
    )
    out: dict[str, str] = {}
    for k in keys:
        v = os.getenv(k)
        if v:
            if k == 'DATABASE_URL' and len(v) > 48:
                out[k] = v[:24] + '…' + v[-12:]
            else:
                out[k] = v
    return out


def network_ips_from_attrs(attrs: dict) -> dict[str, str]:
    nets = ((attrs or {}).get('NetworkSettings') or {}).get('Networks') or {}
    if not isinstance(nets, dict):
        return {}
    ips: dict[str, str] = {}
    for net_name, data in nets.items():
        if isinstance(data, dict):
            ip = (data.get('IPAddress') or '').strip()
            if ip:
                ips[str(net_name)] = ip
    return ips


def list_mail_related_containers(*, limit: int = 80) -> dict[str, Any]:
    """Docker API ile postfix/dovecot/postgres/redis/jir/mail adaylarını listeler."""
    rows: list[dict[str, Any]] = []
    err: str | None = None
    ping = False
    try:
        import docker

        dh = getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock'
        client = docker.DockerClient(base_url=dh, timeout=10)
        client.ping()
        ping = True
        needles = ('postfix', 'dovecot', 'smtp', 'imap', 'redis', 'postgres', 'jir_', 'mail', 'mta')
        for c in client.containers.list(all=True):
            nm = (c.name or '').lower()
            img = ''
            try:
                img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
            except Exception:
                pass
            if not any(x in nm or x in img for x in needles):
                continue
            c.reload()
            attrs = c.attrs or {}
            labs = (attrs.get('Config') or {}).get('Labels') or {}
            compose_svc = ''
            if isinstance(labs, dict):
                compose_svc = (labs.get('com.docker.compose.service') or '').strip()
            rows.append({
                'name': c.name,
                'status': getattr(c, 'status', ''),
                'image': (img or '')[:200],
                'compose_service': compose_svc,
                'network_ips': network_ips_from_attrs(attrs),
            })
        client.close()
    except Exception as exc:
        err = str(exc)

    rows.sort(key=lambda x: (x.get('name') or '').lower())
    return {
        'docker_ping': ping,
        'docker_error': err,
        'containers': rows[:limit],
    }


def mail_tcp_endpoints() -> dict[str, Any]:
    """Panel sürecinden görülen SMTP/IMAP hedefleri (env → DNS → localhost → köprü IP)."""
    smtp_h, smtp_p = resolve_mail_endpoint(
        'postfix',
        int(getattr(settings, 'SMTP_PORT', 587)),
        auth_submission=True,
    )
    imap_h, imap_p = resolve_mail_endpoint(
        'dovecot',
        int(getattr(settings, 'IMAP_PORT', 993)),
    )
    return {
        'smtp_submission': {
            'host': smtp_h,
            'port': smtp_p,
            'tcp_ok': tcp_reachable(smtp_h, smtp_p, timeout=2.5),
        },
        'imap': {
            'host': imap_h,
            'port': imap_p,
            'tcp_ok': tcp_reachable(imap_h, imap_p, timeout=2.5),
        },
    }


def suggested_coolify_env_block(inv: dict[str, Any]) -> str:
    """Kopyala-yapıştır için örnek env bloğu."""
    merged_pf = merged_container_name('postfix')
    merged_dc = merged_container_name('dovecot')
    lines = [
        '# Coolify → Django uygulaması → Environment (örnek — gerçek adları listeden seçin)',
        f'JIR_CONTAINER_POSTFIX={merged_pf}',
        f'JIR_CONTAINER_DOVECOT={merged_dc}',
        '# Opsiyonel: DNS yerine doğrudan host (köprü IP veya servis adı)',
        '# SMTP_HOST=...',
        '# SMTP_PORT=587',
        '# IMAP_HOST=...',
        '# IMAP_PORT=993',
    ]
    cts = inv.get('containers') or []
    pf_candidates = [c['name'] for c in cts if 'postfix' in (c.get('name') or '').lower() or 'smtp' in (c.get('image') or '')]
    dc_candidates = [c['name'] for c in cts if 'dovecot' in (c.get('name') or '').lower() or 'imap' in (c.get('image') or '')]
    if pf_candidates:
        lines.append(f'# Docker listesinde Postfix adayları: {", ".join(pf_candidates[:8])}')
    if dc_candidates:
        lines.append(f'# Docker listesinde Dovecot adayları: {", ".join(dc_candidates[:8])}')
    return '\n'.join(lines)


def network_overlap_hint(containers: list[dict[str, Any]]) -> str:
    """Panel ile postfix/dovecot ortak Docker ağında mı — kısa Türkçe not."""
    coolify_nm = (os.getenv('COOLIFY_CONTAINER_NAME') or '').strip()
    if not coolify_nm or not containers:
        return ''
    panel_nets: set[str] = set()
    for c in containers:
        name = (c.get('name') or '')
        if name == coolify_nm or coolify_nm in name:
            panel_nets = set((c.get('network_ips') or {}).keys())
            break
    if not panel_nets:
        return ''
    shared: list[str] = []
    for c in containers:
        nm = (c.get('name') or '').lower()
        if 'postfix' not in nm and 'dovecot' not in nm:
            continue
        nets = set((c.get('network_ips') or {}).keys())
        inter = panel_nets & nets
        if inter:
            shared.append(f"{c.get('name')} ↔ {', '.join(sorted(inter))}")
    if shared:
        return 'Ortak ağ (panel ↔ mail): ' + '; '.join(shared)
    return (
        'Panel ile Postfix/Dovecot aynı Docker ağında görünmüyor; '
        'SMTP_HOST / IMAP_HOST veya Coolify’da ortak network bağlayın.'
    )


def collect_full_discovery_report() -> dict[str, Any]:
    """CLI ve API için birleşik rapor."""
    inv = list_mail_related_containers()
    endpoints = mail_tcp_endpoints()
    overlap_hint = network_overlap_hint(inv.get('containers') or [])
    resolved = {sk: merged_container_name(sk) for sk in ('postfix', 'dovecot', 'postgres', 'redis')}

    return {
        'platform_env': relevant_platform_env(),
        'merged_container_names': resolved,
        'stored_docker_container_map': read_stored_container_map(),
        'docker_inventory': inv,
        'mail_tcp': endpoints,
        'suggested_env_snippet': suggested_coolify_env_block(inv),
        'network_overlap_hint': overlap_hint,
        'readme': 'Sunucuda ayrıca: docker ps --format "{{.Names}}\\t{{.Image}}\\t{{.Status}}"',
    }
