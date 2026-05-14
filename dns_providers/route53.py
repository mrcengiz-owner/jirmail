"""AWS Route53 DNS provider (boto3 ile).

Gereken credentials:
    aws_access_key_id, aws_secret_access_key, region_name (opsiyonel)

boto3 sadece bu modül kullanılıyorsa import edilir.
"""
from __future__ import annotations

from .base import DNSProvider, DNSRecord


class Route53Provider(DNSProvider):
    name = 'route53'
    display_name = 'AWS Route53'

    def is_configured(self) -> bool:
        return bool(self.credentials.get('aws_access_key_id') and self.credentials.get('aws_secret_access_key'))

    def _get_client(self):
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError(
                'boto3 yüklü değil. requirements.txt veya pip install boto3 ile ekleyin.'
            ) from exc
        return boto3.client(
            'route53',
            aws_access_key_id=self.credentials['aws_access_key_id'],
            aws_secret_access_key=self.credentials['aws_secret_access_key'],
            region_name=self.credentials.get('region_name', 'us-east-1'),
        )

    def _get_hosted_zone_id(self, zone: str) -> str:
        client = self._get_client()
        zone_name = zone if zone.endswith('.') else zone + '.'
        paginator = client.get_paginator('list_hosted_zones')
        for page in paginator.paginate():
            for hz in page.get('HostedZones', []):
                if hz['Name'] == zone_name:
                    return hz['Id'].split('/')[-1]
        raise RuntimeError(f'Hosted zone bulunamadı: {zone}')

    def create_record(self, zone: str, record: DNSRecord) -> dict:
        try:
            client = self._get_client()
            zone_id = self._get_hosted_zone_id(zone)
            full_name = record.name if record.name and record.name != '@' else zone
            if not full_name.endswith('.'):
                full_name += '.'

            value = record.content
            if record.type == 'MX' and record.priority is not None:
                value = f'{record.priority} {record.content}'
            if record.type == 'TXT' and not value.startswith('"'):
                value = f'"{value}"'

            response = client.change_resource_record_sets(
                HostedZoneId=zone_id,
                ChangeBatch={
                    'Changes': [{
                        'Action': 'UPSERT',
                        'ResourceRecordSet': {
                            'Name': full_name,
                            'Type': record.type,
                            'TTL': record.ttl,
                            'ResourceRecords': [{'Value': value}],
                        }
                    }]
                }
            )
            change_id = response['ChangeInfo']['Id']
            return {'success': True, 'id': change_id, 'message': 'Kayıt eklendi/güncellendi'}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}

    def delete_record(self, zone: str, record_id: str) -> dict:
        return {
            'success': False,
            'message': 'Route53 silme için tam kayıt bilgisi gerekiyor. Web konsoldan silin.',
        }
