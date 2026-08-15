"""DNS provider abstract base."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DNSRecord:
    """DNS kayıt verisi."""
    name: str
    type: str
    content: str
    ttl: int = 3600
    priority: int | None = None

    def to_dict(self) -> dict:
        d = {'name': self.name, 'type': self.type, 'content': self.content, 'ttl': self.ttl}
        if self.priority is not None:
            d['priority'] = self.priority
        return d


class DNSProvider(ABC):
    """DNS provider için abstract base.

    Kullanım:
        provider = get_provider('cloudflare', {'api_token': '...'})
        provider.create_record('jircode.com', DNSRecord('mail', 'A', '1.2.3.4'))
        provider.verify_record('jircode.com', DNSRecord('mail', 'A', '1.2.3.4'))
    """

    name: str = 'base'
    display_name: str = 'Base Provider'
    requires_credentials: bool = True

    def __init__(self, credentials: dict):
        self.credentials = credentials or {}

    @abstractmethod
    def is_configured(self) -> bool:
        """Provider'a bağlanmak için yeterli kimlik bilgisi var mı?"""
        ...

    @abstractmethod
    def create_record(self, zone: str, record: DNSRecord) -> dict:
        """Zone'a yeni kayıt ekle. {'success': bool, 'message': str, 'id': str?} döner."""
        ...

    @abstractmethod
    def delete_record(self, zone: str, record_id: str) -> dict:
        """Kayıt id'sine göre sil."""
        ...

    def ensure_record(self, zone: str, record: DNSRecord) -> dict:
        """Varsayılan: create_record. Provider upsert destekliyorsa override eder."""
        return self.create_record(zone, record)

    def verify_record(self, zone: str, record: DNSRecord) -> dict:
        """Kayıt gerçekten DNS'te yayılmış mı kontrol et (dnspython ile)."""
        try:
            import dns.resolver
            resolver = dns.resolver.Resolver()
            resolver.timeout = 5
            resolver.lifetime = 10
            full_name = record.name if record.name.endswith(zone) else f'{record.name}.{zone}'.lstrip('.')
            if record.name == '@' or record.name == '':
                full_name = zone

            answers = resolver.resolve(full_name, record.type)
            for answer in answers:
                if record.content.strip('"') in answer.to_text().strip('"'):
                    return {'success': True, 'verified': True}
            return {'success': True, 'verified': False, 'message': 'Kayıt bulundu ama içerik eşleşmedi'}
        except Exception as exc:
            return {'success': False, 'verified': False, 'message': str(exc)}
