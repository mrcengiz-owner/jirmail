"""Cloudflare DNS provider (API v4).

Gereken credentials:
    api_token: Cloudflare API Token (Zone:Read, DNS:Edit yetkisi olan)
"""
from __future__ import annotations

import urllib.parse
import urllib.request
import json
import ssl

from .base import DNSProvider, DNSRecord


API_BASE = 'https://api.cloudflare.com/client/v4'


def _api_request(method: str, url: str, token: str, payload: dict | None = None) -> dict:
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
    }
    body = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return json.loads(resp.read().decode('utf-8'))


class CloudflareProvider(DNSProvider):
    name = 'cloudflare'
    display_name = 'Cloudflare'

    def is_configured(self) -> bool:
        return bool(self.credentials.get('api_token'))

    def _get_zone_id(self, zone: str) -> str:
        token = self.credentials['api_token']
        url = f'{API_BASE}/zones?name={urllib.parse.quote(zone)}'
        data = _api_request('GET', url, token)
        if not data.get('success'):
            raise RuntimeError(f'Cloudflare zone fetch failed: {data}')
        result = data.get('result', [])
        if not result:
            raise RuntimeError(f'Zone bulunamadı: {zone}')
        return result[0]['id']

    def create_record(self, zone: str, record: DNSRecord) -> dict:
        try:
            token = self.credentials['api_token']
            zone_id = self._get_zone_id(zone)

            payload = {
                'type': record.type,
                'name': record.name if record.name and record.name != '@' else zone,
                'content': record.content,
                'ttl': record.ttl,
            }
            if record.type == 'MX' and record.priority is not None:
                payload['priority'] = record.priority

            url = f'{API_BASE}/zones/{zone_id}/dns_records'
            data = _api_request('POST', url, token, payload)
            if data.get('success'):
                return {'success': True, 'id': data['result']['id'], 'message': 'Kayıt eklendi'}
            return {'success': False, 'message': str(data.get('errors', data))}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}

    def delete_record(self, zone: str, record_id: str) -> dict:
        try:
            token = self.credentials['api_token']
            zone_id = self._get_zone_id(zone)
            url = f'{API_BASE}/zones/{zone_id}/dns_records/{record_id}'
            data = _api_request('DELETE', url, token)
            if data.get('success'):
                return {'success': True, 'message': 'Kayıt silindi'}
            return {'success': False, 'message': str(data.get('errors', data))}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}
