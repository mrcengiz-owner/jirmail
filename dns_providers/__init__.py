"""DNS provider adaptörleri.

Her provider, ortak bir DNSProvider abstract sınıfını implement eder.
Setup wizard kullanıcının token'ını alır ve uygun adaptörü seçer.
"""
from .base import DNSProvider, DNSRecord
from .manual import ManualProvider
from .cloudflare import CloudflareProvider
from .route53 import Route53Provider
from .namecheap import NamecheapProvider


PROVIDER_REGISTRY: dict[str, type[DNSProvider]] = {
    'manual': ManualProvider,
    'cloudflare': CloudflareProvider,
    'route53': Route53Provider,
    'namecheap': NamecheapProvider,
}


def get_provider(name: str, credentials: dict | None = None) -> DNSProvider:
    """Provider adından ilgili adaptör örneğini üretir."""
    name = (name or 'manual').lower()
    if name not in PROVIDER_REGISTRY:
        raise ValueError(f'Bilinmeyen DNS provider: {name}')
    return PROVIDER_REGISTRY[name](credentials or {})


__all__ = ['DNSProvider', 'DNSRecord', 'get_provider', 'PROVIDER_REGISTRY']
