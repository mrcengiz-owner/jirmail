"""DNSBL (DNS Blacklist) kontrol modülü.

Sunucu IP'sinin Spamhaus, SORBS, Barracuda gibi blacklist'lerde listelenip
listelenmediğini kontrol eder.
"""
from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)


DNSBL_PROVIDERS = [
    {'name': 'Spamhaus ZEN', 'host': 'zen.spamhaus.org'},
    {'name': 'SpamCop', 'host': 'bl.spamcop.net'},
    {'name': 'SORBS', 'host': 'dnsbl.sorbs.net'},
    {'name': 'Barracuda', 'host': 'b.barracudacentral.org'},
    {'name': 'Mailspike Z', 'host': 'z.mailspike.net'},
    {'name': 'PSBL', 'host': 'psbl.surriel.com'},
    {'name': 'UCEPROTECT-1', 'host': 'dnsbl-1.uceprotect.net'},
]


def _reverse_ip(ip: str) -> str:
    return '.'.join(reversed(ip.split('.')))


def check_ip(ip: str, *, providers: list[dict] | None = None, timeout: float = 5.0) -> dict:
    """Verilen IP'nin DNSBL'lerde listelenip listelenmediğini kontrol et."""
    try:
        ipaddress.IPv4Address(ip)
    except Exception:
        return {'success': False, 'message': f'Geçersiz IPv4: {ip}'}

    try:
        import dns.resolver
    except ImportError:
        return {'success': False, 'message': 'dnspython yüklü değil'}

    providers = providers or DNSBL_PROVIDERS
    reverse = _reverse_ip(ip)
    results: list[dict] = []

    resolver = dns.resolver.Resolver()
    resolver.timeout = timeout
    resolver.lifetime = timeout * 2

    listed_count = 0
    for provider in providers:
        query = f'{reverse}.{provider["host"]}'
        item: dict = {'provider': provider['name'], 'host': provider['host'], 'listed': False, 'reason': ''}

        try:
            answers = resolver.resolve(query, 'A')
            answer_codes = [str(r) for r in answers]
            item['listed'] = True
            item['answer'] = answer_codes
            listed_count += 1

            try:
                txt = resolver.resolve(query, 'TXT')
                item['reason'] = ' | '.join(str(r).strip('"') for r in txt)
            except Exception:
                pass

        except dns.resolver.NXDOMAIN:
            item['listed'] = False
        except Exception as exc:
            item['error'] = str(exc)

        results.append(item)

    return {
        'success': True,
        'ip': ip,
        'total_providers': len(providers),
        'listed_count': listed_count,
        'clean': listed_count == 0,
        'results': results,
    }
