"""Manuel provider — admin kayıtları elle ekler, sistem sadece doğrular."""
from __future__ import annotations

from .base import DNSProvider, DNSRecord


class ManualProvider(DNSProvider):
    name = 'manual'
    display_name = 'Manuel (kopyala-yapıştır)'
    requires_credentials = False

    def is_configured(self) -> bool:
        return True

    def create_record(self, zone: str, record: DNSRecord) -> dict:
        return {
            'success': False,
            'message': 'Manuel modda kayıt otomatik eklenmez. Lütfen kaydı registar panelinden ekleyin.',
            'manual_instruction': record.to_dict(),
        }

    def delete_record(self, zone: str, record_id: str) -> dict:
        return {
            'success': False,
            'message': 'Manuel modda silme yok. Lütfen kaydı registar panelinden silin.',
        }
