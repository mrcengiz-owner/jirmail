"""Mail için gereken DNS kayıtlarını tek yerden üretir."""
from __future__ import annotations

import logging
import os
import re
import ssl
import urllib.request
from typing import Any

from .base import DNSRecord

logger = logging.getLogger(__name__)


def detect_public_ip(*, preferred: str = '') -> str | None:
    """Sunucunun genel IP'sini bul (env → tercih → dış servisler)."""
    for candidate in (
        (preferred or '').strip(),
        (os.getenv('SERVER_PUBLIC_IP') or '').strip(),
        (os.getenv('PUBLIC_IP') or '').strip(),
        (os.getenv('MAIL_SERVER_IP') or '').strip(),
    ):
        if candidate and candidate.upper() not in ('SUNUCU_IP', 'YOUR_IP', '0.0.0.0'):
            return candidate

    ctx = ssl.create_default_context()
    for url in (
        'https://api.ipify.org',
        'https://ifconfig.me/ip',
        'https://icanhazip.com',
    ):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'jirmail-dns/1.0'})
            with urllib.request.urlopen(req, timeout=5, context=ctx) as resp:
                ip = resp.read().decode('utf-8', errors='replace').strip()
            if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
                return ip
        except Exception as exc:
            logger.debug('public IP lookup %s: %s', url, exc)
    return None


def parse_dkim_dns(domain_obj) -> tuple[str, str] | None:
    """
    MailDomain.dkim_record → (relative_name, txt_content).
    Örnek kayıt: mail-abcd._domainkey.example.com IN TXT "v=DKIM1; k=rsa; p=..."
    """
    raw = (getattr(domain_obj, 'dkim_record', None) or '').strip()
    if not raw:
        return None

    name_part = raw
    content = ''
    if ' IN TXT ' in raw.upper():
        # case-insensitive split
        idx = raw.upper().index(' IN TXT ')
        name_part = raw[:idx].strip()
        content = raw[idx + len(' IN TXT '):].strip().strip('"')
    elif '"' in raw:
        # "content" only fallback
        m = re.search(r'"([^"]+)"', raw)
        if m:
            content = m.group(1)
        name_part = raw.split('"', 1)[0].strip()

    domain_name = (getattr(domain_obj, 'name', '') or '').lower()
    name_part = name_part.rstrip('.')
    if domain_name and name_part.lower().endswith('.' + domain_name):
        name_part = name_part[: -(len(domain_name) + 1)]

    if not content and 'v=DKIM1' in raw:
        content = raw.strip().strip('"')

    if not name_part or not content:
        return None
    if not content.startswith('v=DKIM1'):
        content = f'v=DKIM1; k=rsa; p={content}' if content.startswith('MII') else content
    return name_part, content


def ensure_domain_dkim(domain_name: str):
    """Domain satırını getir/oluştur ve DKIM yoksa üret."""
    from core.models import MailDomain

    domain_obj, _ = MailDomain.objects.get_or_create(
        name=domain_name.lower().strip(),
        defaults={'is_active': True},
    )
    if not domain_obj.dkim_private_key or not domain_obj.dkim_record:
        domain_obj.generate_dkim_keys()
    elif not domain_obj.spf_record or not domain_obj.dmarc_record:
        mail_host = f'mail.{domain_obj.name}'
        domain_obj.spf_record = domain_obj.spf_record or f'v=spf1 mx a:{mail_host} -all'
        domain_obj.dmarc_record = (
            domain_obj.dmarc_record
            or f'v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain_obj.name}'
        )
        domain_obj.save(update_fields=['spf_record', 'dmarc_record'])
    return domain_obj


def build_mail_dns_records(
    domain: str,
    *,
    server_ip: str = '',
    mail_hostname: str = '',
    domain_obj=None,
    include_client_discovery: bool = True,
) -> list[DNSRecord]:
    """
    Mail zone için tam kayıt seti:
    A (mail), MX, SPF, DMARC, DKIM [+ opsiyonel autoconfig/autodiscover CNAME].
    """
    domain = (domain or '').strip().lower()
    if not domain:
        raise ValueError('domain gerekli')

    mail_host = (mail_hostname or '').strip().lower() or f'mail.{domain}'
    if mail_host.endswith('.' + domain):
        mail_label = mail_host[: -(len(domain) + 1)] or 'mail'
    elif mail_host == domain:
        mail_label = '@'
    else:
        mail_label = mail_host.split('.')[0] or 'mail'

    ip = detect_public_ip(preferred=server_ip)
    if not ip:
        ip = (server_ip or '').strip() or None

    if domain_obj is None:
        try:
            domain_obj = ensure_domain_dkim(domain)
        except Exception:
            domain_obj = None

    spf = f'v=spf1 mx a:{mail_host} -all'
    dmarc = f'v=DMARC1; p=quarantine; rua=mailto:dmarc@{domain}'
    if domain_obj:
        # Model ile senkron tut (a:mail.host tercih edilir)
        if not domain_obj.spf_record or 'v=spf1' in domain_obj.spf_record:
            domain_obj.spf_record = spf
        else:
            spf = domain_obj.spf_record
        if domain_obj.dmarc_record:
            dmarc = domain_obj.dmarc_record
        else:
            domain_obj.dmarc_record = dmarc
        try:
            domain_obj.save(update_fields=['spf_record', 'dmarc_record'])
        except Exception:
            pass

    records: list[DNSRecord] = []

    if ip and ip.upper() not in ('SUNUCU_IP', 'YOUR_IP'):
        records.append(DNSRecord(name=mail_label, type='A', content=ip, ttl=300))
    else:
        logger.warning('Mail A kaydı için public IP bulunamadı — A atlanacak (%s)', domain)

    records.append(DNSRecord(name='@', type='MX', content=mail_host, ttl=3600, priority=10))
    records.append(DNSRecord(name='@', type='TXT', content=spf, ttl=3600))
    records.append(DNSRecord(name='_dmarc', type='TXT', content=dmarc, ttl=3600))

    if domain_obj:
        dkim = parse_dkim_dns(domain_obj)
        if dkim:
            records.append(DNSRecord(name=dkim[0], type='TXT', content=dkim[1], ttl=3600))

    if include_client_discovery and mail_label not in ('@', ''):
        # İstemci keşfi — çoğu panel/desktop client
        records.append(DNSRecord(name='autoconfig', type='CNAME', content=mail_host, ttl=3600))
        records.append(DNSRecord(name='autodiscover', type='CNAME', content=mail_host, ttl=3600))

    return records


def records_as_dicts(records: list[DNSRecord]) -> list[dict[str, Any]]:
    out = []
    descriptions = {
        ('A', 'mail'): 'Mail sunucusu A kaydı (SMTP/IMAP hostname)',
        ('MX', '@'): 'MX — gelen posta yönlendirmesi',
        ('TXT', '@'): 'SPF — yetkili gönderenler',
        ('TXT', '_dmarc'): 'DMARC politikası',
        ('CNAME', 'autoconfig'): 'Thunderbird vb. otomatik yapılandırma',
        ('CNAME', 'autodiscover'): 'Outlook otomatik yapılandırma',
    }
    for r in records:
        d = r.to_dict()
        key = (r.type, r.name.split('.')[0] if '._domainkey' not in r.name else 'dkim')
        if '._domainkey' in r.name:
            d['description'] = 'DKIM public key'
        else:
            d['description'] = descriptions.get((r.type, r.name), f'{r.type} {r.name}')
        out.append(d)
    return out


def summarize_dns_results(results: list[dict]) -> str:
    """Başarısız kayıtlardan okunabilir hata özeti üret."""
    failures: list[str] = []
    for item in results or []:
        res = item.get('result') or {}
        if res.get('success'):
            continue
        rec = item.get('record') or {}
        label = f"{rec.get('type', '?')} {rec.get('name', '?')}"
        msg = (res.get('message') or 'bilinmeyen hata').strip()
        if len(msg) > 180:
            msg = msg[:177] + '...'
        failures.append(f'{label}: {msg}')
    if not failures:
        return 'DNS uygulanamadı'
    if len(failures) == 1:
        return failures[0]
    return failures[0] + f' (+{len(failures) - 1} kayıt daha)'


def apply_mail_dns(
    domain: str,
    *,
    provider_name: str,
    credentials: dict | None = None,
    server_ip: str = '',
    mail_hostname: str = '',
    domain_obj=None,
) -> dict[str, Any]:
    """Provider üzerinden tüm mail DNS kayıtlarını oluştur/güncelle."""
    from . import get_provider

    domain_obj = domain_obj or ensure_domain_dkim(domain)
    provider = get_provider(provider_name, credentials or {})
    if (provider_name or 'manual').lower() == 'manual' or not provider.is_configured():
        return {
            'success': True,
            'skipped': True,
            'message': 'Manuel DNS — kayıtlar panoda gösterilecek',
            'records': records_as_dicts(
                build_mail_dns_records(
                    domain,
                    server_ip=server_ip,
                    mail_hostname=mail_hostname,
                    domain_obj=domain_obj,
                )
            ),
            'results': [],
        }

    # Cloudflare: token/zone erişimini erken doğrula
    if (provider_name or '').lower() == 'cloudflare':
        verify = getattr(provider, 'verify_mail_domain', None)
        if callable(verify):
            check = verify(domain)
            if not check.get('success'):
                return {
                    'success': False,
                    'skipped': False,
                    'partial': False,
                    'total': 0,
                    'created': 0,
                    'results': [],
                    'message': check.get('message') or 'Cloudflare zone/token hatası',
                    'records': [],
                }

    records = build_mail_dns_records(
        domain,
        server_ip=server_ip,
        mail_hostname=mail_hostname,
        domain_obj=domain_obj,
    )
    results: list[dict] = []
    ensure = getattr(provider, 'ensure_record', None) or provider.create_record
    for rec in records:
        outcome = ensure(domain, rec)
        results.append({'record': rec.to_dict(), 'result': outcome})

    domain_obj.dns_provider = (provider_name or 'manual').lower()
    domain_obj.dns_credentials = credentials or {}
    domain_obj.save(update_fields=['dns_provider', 'dns_credentials', 'spf_record', 'dmarc_record', 'dkim_record'])

    ok = sum(1 for r in results if r['result'].get('success'))
    summary = summarize_dns_results(results)
    return {
        'success': ok == len(results) and len(results) > 0,
        'partial': 0 < ok < len(results),
        'total': len(results),
        'created': ok,
        'results': results,
        'records': records_as_dicts(records),
        'server_ip': detect_public_ip(preferred=server_ip),
        'message': summary if ok < len(results) else 'Tüm DNS kayıtları uygulandı',
    }
