"""Cloudflare DNS provider (API v4).

Gereken credentials:
    api_token: Cloudflare API Token (Zone:Read, DNS:Edit yetkisi olan)
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

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
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            return json.loads(raw)
        except Exception:
            raise RuntimeError(f'Cloudflare HTTP {exc.code}: {raw[:300]}') from exc


class CloudflareProvider(DNSProvider):
    name = 'cloudflare'
    display_name = 'Cloudflare'

    def is_configured(self) -> bool:
        return bool(self.credentials.get('api_token'))

    def _token(self) -> str:
        return self.credentials['api_token']

    def _get_zone_id(self, zone: str) -> str:
        token = self._token()
        url = f'{API_BASE}/zones?name={urllib.parse.quote(zone)}'
        data = _api_request('GET', url, token)
        if not data.get('success'):
            raise RuntimeError(f'Cloudflare zone fetch failed: {data.get("errors") or data}')
        result = data.get('result', [])
        if not result:
            raise RuntimeError(f'Zone bulunamadı: {zone} (token Zone:Read + doğru hesap?)')
        return result[0]['id']

    def _fqdn(self, zone: str, record: DNSRecord) -> str:
        if not record.name or record.name in ('@', ''):
            return zone
        if record.name.endswith('.' + zone) or record.name == zone:
            return record.name
        return f'{record.name}.{zone}'

    def _list_matching(self, zone_id: str, zone: str, record: DNSRecord) -> list[dict]:
        token = self._token()
        name = self._fqdn(zone, record)
        qs = urllib.parse.urlencode({'type': record.type, 'name': name, 'per_page': 50})
        url = f'{API_BASE}/zones/{zone_id}/dns_records?{qs}'
        data = _api_request('GET', url, token)
        if not data.get('success'):
            return []
        return list(data.get('result') or [])

    def _payload(self, zone: str, record: DNSRecord) -> dict:
        payload: dict = {
            'type': record.type,
            'name': self._fqdn(zone, record),
            'content': record.content,
            'ttl': record.ttl or 3600,
        }
        # Mail kayıtları proxied olmamalı (SMTP/IMAP kırılır)
        if record.type in ('A', 'AAAA', 'CNAME'):
            payload['proxied'] = False
        if record.type == 'MX' and record.priority is not None:
            payload['priority'] = record.priority
        return payload

    def create_record(self, zone: str, record: DNSRecord) -> dict:
        return self.ensure_record(zone, record)

    def ensure_record(self, zone: str, record: DNSRecord) -> dict:
        """Yoksa oluştur, varsa güncelle (upsert)."""
        try:
            token = self._token()
            zone_id = self._get_zone_id(zone)
            payload = self._payload(zone, record)
            existing = self._list_matching(zone_id, zone, record)

            # Aynı içerik varsa dokunma
            for item in existing:
                same_content = (item.get('content') or '') == record.content
                same_prio = True
                if record.type == 'MX':
                    same_prio = int(item.get('priority') or 0) == int(record.priority or 0)
                if same_content and same_prio:
                    return {
                        'success': True,
                        'id': item.get('id'),
                        'message': 'Kayıt zaten güncel',
                        'action': 'unchanged',
                    }

            if existing:
                rid = existing[0]['id']
                url = f'{API_BASE}/zones/{zone_id}/dns_records/{rid}'
                data = _api_request('PUT', url, token, payload)
                if data.get('success'):
                    return {
                        'success': True,
                        'id': rid,
                        'message': 'Kayıt güncellendi',
                        'action': 'updated',
                    }
                return {'success': False, 'message': str(data.get('errors') or data)}

            url = f'{API_BASE}/zones/{zone_id}/dns_records'
            data = _api_request('POST', url, token, payload)
            if data.get('success'):
                return {
                    'success': True,
                    'id': (data.get('result') or {}).get('id'),
                    'message': 'Kayıt eklendi',
                    'action': 'created',
                }
            return {'success': False, 'message': str(data.get('errors') or data)}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}

    def delete_record(self, zone: str, record_id: str) -> dict:
        try:
            token = self._token()
            zone_id = self._get_zone_id(zone)
            url = f'{API_BASE}/zones/{zone_id}/dns_records/{record_id}'
            data = _api_request('DELETE', url, token)
            if data.get('success'):
                return {'success': True, 'message': 'Kayıt silindi'}
            return {'success': False, 'message': str(data.get('errors', data))}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}
