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
        seen_names: set[str] = set()

        def append_container(c, *, force: bool = False) -> None:
            nm = (c.name or '').strip()
            if not nm or nm in seen_names:
                return
            if not force:
                nm_l = nm.lower()
                img = ''
                try:
                    img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
                except Exception:
                    pass
                if not any(x in nm_l or x in img for x in needles):
                    return
            seen_names.add(nm)
            c.reload()
            attrs = c.attrs or {}
            labs = (attrs.get('Config') or {}).get('Labels') or {}
            compose_svc = ''
            if isinstance(labs, dict):
                compose_svc = (labs.get('com.docker.compose.service') or '').strip()
            rows.append({
                'name': c.name,
                'status': getattr(c, 'status', ''),
                'image': (
                    (((attrs.get('Config') or {}).get('Image') or '') or '')[:200]
                ),
                'compose_service': compose_svc,
                'network_ips': network_ips_from_attrs(attrs),
                'is_panel': force,
            })

        panel_nm = (os.getenv('COOLIFY_CONTAINER_NAME') or '').strip()
        if panel_nm:
            try:
                append_container(client.containers.get(panel_nm), force=True)
            except Exception:
                pass

        for c in client.containers.list(all=True):
            nm = (c.name or '').lower()
            img = ''
            try:
                img = (((c.attrs or {}).get('Config') or {}).get('Image') or '').lower()
            except Exception:
                pass
            append_container(c)
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


def _pick_mail_host_candidate(ct: dict[str, Any]) -> str:
    """SMTP/IMAP için öncelik: compose service adı, sonra konteyner adı."""
    svc = (ct.get('compose_service') or '').strip()
    if svc:
        return svc
    return (ct.get('name') or '').strip()


def suggested_coolify_env_block(inv: dict[str, Any]) -> str:
    """Kopyala-yapıştır için örnek env bloğu."""
    merged_pf = merged_container_name('postfix')
    merged_dc = merged_container_name('dovecot')
    cts = inv.get('containers') or []
    pf_rows = _mail_service_rows(cts, 'postfix')
    dc_rows = _mail_service_rows(cts, 'dovecot')
    analysis = analyze_mail_network_connectivity(cts)

    smtp_host = (analysis.get('suggested_smtp_host') or '').strip()
    imap_host = (analysis.get('suggested_imap_host') or '').strip()
    if not smtp_host and pf_rows:
        smtp_host = _pick_mail_host_candidate(pf_rows[0])
    if not imap_host and dc_rows:
        imap_host = _pick_mail_host_candidate(dc_rows[0])

    lines = [
        '# Coolify → Django uygulaması → Environment (kaydet + redeploy)',
        f'JIR_CONTAINER_POSTFIX={pf_rows[0]["name"] if pf_rows else merged_pf}',
        f'JIR_CONTAINER_DOVECOT={dc_rows[0]["name"] if dc_rows else merged_dc}',
    ]
    if analysis.get('split_network'):
        lines.append(
            '# ÖNEMLİ: Panel coolify ağında, mail jir_network’te — önce uygulamayı jir_network’e bağlayın;'
        )
        lines.append(
            '# sonra aşağıdaki SMTP_HOST=jir_postfix kullanın. IP geçici test içindir.'
        )
    if smtp_host:
        lines.extend([
            f'SMTP_HOST={smtp_host}',
            'SMTP_PORT=587',
        ])
    else:
        lines.extend([
            '# Postfix yok — önce mail stack deploy',
            '# SMTP_HOST=jir_postfix',
            '# SMTP_PORT=587',
        ])
    if imap_host:
        lines.extend([
            f'IMAP_HOST={imap_host}',
            'IMAP_PORT=993',
        ])
    else:
        lines.extend([
            '# IMAP_HOST=jir_dovecot',
            '# IMAP_PORT=993',
        ])
    if analysis.get('shared_networks'):
        lines.append(
            '# Ortak ağ var — kalıcı: SMTP_HOST=jir_postfix IMAP_HOST=jir_dovecot (DNS adları)'
        )
    jir_ips = analysis.get('jir_network_mail_ips') or {}
    pf_ips = jir_ips.get('postfix') or {}
    dc_ips = jir_ips.get('dovecot') or {}
    if pf_ips:
        lines.append(f'# jir_network Postfix IP: {", ".join(f"{n}={ip}" for n, ip in pf_ips.items())}')
    if dc_ips:
        lines.append(f'# jir_network Dovecot IP: {", ".join(f"{n}={ip}" for n, ip in dc_ips.items())}')
    return '\n'.join(lines)


def _panel_container_row(containers: list[dict[str, Any]]) -> dict[str, Any] | None:
    coolify_nm = (os.getenv('COOLIFY_CONTAINER_NAME') or '').strip()
    if not coolify_nm:
        return None
    for c in containers:
        name = (c.get('name') or '')
        if name == coolify_nm or coolify_nm in name:
            return c
    return None


def _mail_service_rows(containers: list[dict[str, Any]], service_key: str) -> list[dict[str, Any]]:
    sk = service_key.strip().lower()
    if sk == 'postfix':
        needles = ('postfix', 'smtp', 'mta')
    else:
        needles = ('dovecot', 'imap')
    out: list[dict[str, Any]] = []
    for c in containers:
        nm = (c.get('name') or '').lower()
        img = (c.get('image') or '').lower()
        if any(n in nm or n in img for n in needles):
            out.append(c)
    return out


def analyze_mail_network_connectivity(containers: list[dict[str, Any]]) -> dict[str, Any]:
    """Panel ↔ Postfix/Dovecot ağ analizi ve Coolify için somut öneriler."""
    panel = _panel_container_row(containers)
    panel_nets = set((panel or {}).get('network_ips') or {})
    pf_rows = _mail_service_rows(containers, 'postfix')
    dc_rows = _mail_service_rows(containers, 'dovecot')

    def mail_on_network(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
        found: dict[str, dict[str, str]] = {}
        for c in rows:
            name = (c.get('name') or '').strip()
            for net, ip in (c.get('network_ips') or {}).items():
                found.setdefault(net, {})[name] = ip
        return found

    mail_nets = mail_on_network(pf_rows + dc_rows)
    shared_nets = sorted(panel_nets & set(mail_nets.keys())) if panel_nets else []

    pf_on_jir = (mail_nets.get('jir_network') or {})
    dc_on_jir = {
        k: v for k, v in (mail_nets.get('jir_network') or {}).items()
        if k in {(c.get('name') or '') for c in dc_rows}
    }
    if not dc_on_jir and dc_rows:
        for c in dc_rows:
            ips = (c.get('network_ips') or {})
            if 'jir_network' in ips:
                dc_on_jir[c['name']] = ips['jir_network']

    split = bool(panel_nets and mail_nets and not shared_nets)

    fixes: list[str] = []
    if split:
        fixes.append(
            'Coolify → uygulama (Django) → Network: mevcut Docker ağına bağlayın: '
            '`jir_network` (external network). Deploy sonrası SMTP_HOST=jir_postfix çalışır.'
        )
        fixes.append(
            'Alternatif: Postfix/Dovecot 587/993 portlarını host’a publish edin; '
            'SMTP_HOST=host.docker.internal veya sunucu iç IP (Coolify sürümüne göre değişir).'
        )
        if pf_on_jir:
            ip = next(iter(pf_on_jir.values()), '')
            fixes.append(
                f'jir_network üzerinde Postfix IP: {ip} — panel coolify ağındayken bu IP’ye '
                f'genelde ulaşılamaz; önce ortak ağ şart.'
            )

    smtp_host_suggest = ''
    imap_host_suggest = ''
    smtp_port = 587
    imap_port = 993

    if pf_rows:
        smtp_host_suggest = _pick_mail_host_candidate(pf_rows[0])
    if dc_rows:
        imap_host_suggest = _pick_mail_host_candidate(dc_rows[0])

    return {
        'panel_container': (panel or {}).get('name') or os.getenv('COOLIFY_CONTAINER_NAME', ''),
        'panel_networks': sorted(panel_nets),
        'mail_networks': {net: list(ips.keys()) for net, ips in mail_nets.items()},
        'shared_networks': shared_nets,
        'split_network': split,
        'jir_network_mail_ips': {'postfix': pf_on_jir, 'dovecot': dc_on_jir},
        'recommended_fixes': fixes,
        'suggested_smtp_host': smtp_host_suggest,
        'suggested_imap_host': imap_host_suggest,
        'suggested_smtp_port': smtp_port,
        'suggested_imap_port': imap_port,
    }


def network_overlap_hint(containers: list[dict[str, Any]]) -> str:
    """Panel ile postfix/dovecot ortak Docker ağında mı — kısa Türkçe not."""
    analysis = analyze_mail_network_connectivity(containers)
    if analysis.get('shared_networks'):
        nets = ', '.join(analysis['shared_networks'])
        return f'Ortak ağ (panel ↔ mail): {nets} — SMTP_HOST=jir_postfix genelde yeterli.'
    if analysis.get('split_network'):
        panel_n = ', '.join(analysis.get('panel_networks') or []) or '?'
        mail_n = ', '.join(sorted((analysis.get('mail_networks') or {}).keys())) or '?'
        return (
            f'Panel ağı ({panel_n}) ile mail ağı ({mail_n}) AYRI — bu yüzden jir_postfix DNS/TCP '
            f'panelden erişilemiyor; Coolify uygulamasını jir_network’e bağlayın.'
        )
    coolify_nm = (os.getenv('COOLIFY_CONTAINER_NAME') or '').strip()
    if not coolify_nm or not containers:
        return ''
    return (
        'Panel konteyneri listede yok veya ağ bilgisi eksik; '
        'SMTP_HOST / IMAP_HOST veya ortak Docker network bağlayın.'
    )


def collect_full_discovery_report() -> dict[str, Any]:
    """CLI ve API için birleşik rapor."""
    inv = list_mail_related_containers()
    endpoints = mail_tcp_endpoints()
    containers = inv.get('containers') or []
    overlap_hint = network_overlap_hint(containers)
    connectivity = analyze_mail_network_connectivity(containers)
    resolved = {sk: merged_container_name(sk) for sk in ('postfix', 'dovecot', 'postgres', 'redis')}

    return {
        'platform_env': relevant_platform_env(),
        'merged_container_names': resolved,
        'stored_docker_container_map': read_stored_container_map(),
        'docker_inventory': inv,
        'mail_tcp': endpoints,
        'network_connectivity': connectivity,
        'suggested_env_snippet': suggested_coolify_env_block(inv),
        'network_overlap_hint': overlap_hint,
        'readme': 'Sunucuda ayrıca: docker ps --format "{{.Names}}\\t{{.Image}}\\t{{.Status}}"',
    }
