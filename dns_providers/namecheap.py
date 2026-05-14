"""Namecheap DNS provider.

Gereken credentials:
    api_user, api_key, username, client_ip

Namecheap API'si IP whitelist gerektirir; client_ip whitelisted olmalı.
"""
from __future__ import annotations

import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from .base import DNSProvider, DNSRecord


API_BASE = 'https://api.namecheap.com/xml.response'


class NamecheapProvider(DNSProvider):
    name = 'namecheap'
    display_name = 'Namecheap'

    def is_configured(self) -> bool:
        c = self.credentials
        return bool(c.get('api_user') and c.get('api_key') and c.get('username') and c.get('client_ip'))

    def _request(self, params: dict) -> ET.Element:
        c = self.credentials
        params = {
            'ApiUser': c['api_user'],
            'ApiKey': c['api_key'],
            'UserName': c['username'],
            'ClientIp': c['client_ip'],
            **params,
        }
        url = f'{API_BASE}?{urllib.parse.urlencode(params)}'
        with urllib.request.urlopen(url, timeout=15) as resp:
            content = resp.read().decode('utf-8')
        return ET.fromstring(content)

    def _split_domain(self, zone: str) -> tuple[str, str]:
        parts = zone.split('.')
        if len(parts) < 2:
            raise ValueError(f'Geçersiz domain: {zone}')
        return parts[0], '.'.join(parts[1:])

    def create_record(self, zone: str, record: DNSRecord) -> dict:
        try:
            sld, tld = self._split_domain(zone)
            host = record.name if record.name and record.name != '@' else '@'

            # Namecheap'te tüm hostları tek istekte göndermek gerek. Önce mevcut listeyi al, sonra üzerine ekle.
            params = {
                'Command': 'namecheap.domains.dns.getHosts',
                'SLD': sld,
                'TLD': tld,
            }
            existing_root = self._request(params)
            ns = {'nc': 'http://api.namecheap.com/xml.response'}
            hosts = []
            i = 1
            for h in existing_root.iter('{http://api.namecheap.com/xml.response}host'):
                hosts.append({
                    'name': h.attrib.get('Name'),
                    'type': h.attrib.get('Type'),
                    'address': h.attrib.get('Address'),
                    'mx_pref': h.attrib.get('MXPref', '10'),
                    'ttl': h.attrib.get('TTL', '3600'),
                })

            hosts.append({
                'name': host,
                'type': record.type,
                'address': record.content,
                'mx_pref': str(record.priority or 10) if record.type == 'MX' else '10',
                'ttl': str(record.ttl),
            })

            set_params: dict[str, str] = {
                'Command': 'namecheap.domains.dns.setHosts',
                'SLD': sld,
                'TLD': tld,
            }
            for idx, h in enumerate(hosts, start=1):
                set_params[f'HostName{idx}'] = h['name'] or '@'
                set_params[f'RecordType{idx}'] = h['type']
                set_params[f'Address{idx}'] = h['address']
                set_params[f'MXPref{idx}'] = h['mx_pref']
                set_params[f'TTL{idx}'] = h['ttl']

            root = self._request(set_params)
            status = root.attrib.get('Status', 'ERROR')
            if status == 'OK':
                return {'success': True, 'message': 'Kayıt eklendi'}
            return {'success': False, 'message': f'Namecheap hatası: {status}'}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}

    def delete_record(self, zone: str, record_id: str) -> dict:
        return {
            'success': False,
            'message': 'Namecheap silme için tüm host listesi yeniden gönderilmeli. Web konsoldan silin.',
        }
