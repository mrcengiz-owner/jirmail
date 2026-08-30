"""Cloudflare DNS provider (API v4).

Desteklenen kimlik bilgileri:
    api_token — API Token (önerilen, Bearer)
    email + api_key — Global API Key (X-Auth-Email / X-Auth-Key)
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .base import DNSProvider, DNSRecord


API_BASE = 'https://api.cloudflare.com/client/v4'


def normalize_cloudflare_credentials(credentials: dict | None) -> dict:
    """Kurulum/panelden gelen alan adlarını standartlaştır."""
    c = dict(credentials or {})
    token = (
        (c.get('api_token') or c.get('token') or c.get('cf_api_token') or '')
    ).strip()
    if not token and c.get('api_key'):
        # Namecheap vb. ile karışmasın — yalnızca email de varsa Global Key say
        email = (c.get('email') or c.get('auth_email') or c.get('cf_email') or '').strip()
        if email:
            c.setdefault('api_key', c.get('api_key'))
            c.setdefault('email', email)
    if token and not c.get('api_token'):
        c['api_token'] = token
    return c


def _format_cf_errors(data: dict) -> str:
    errors = data.get('errors') or data.get('messages') or data
    if isinstance(errors, list):
        parts = []
        for item in errors:
            if isinstance(item, dict):
                code = item.get('code')
                msg = item.get('message') or str(item)
                parts.append(f'[{code}] {msg}' if code else msg)
            else:
                parts.append(str(item))
        return '; '.join(parts) or str(data)
    return str(errors)


def _auth_headers(credentials: dict) -> dict:
    creds = normalize_cloudflare_credentials(credentials)
    token = (creds.get('api_token') or '').strip()
    if token:
        return {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
    email = (creds.get('email') or creds.get('auth_email') or '').strip()
    api_key = (creds.get('api_key') or creds.get('global_api_key') or '').strip()
    if email and api_key:
        return {
            'X-Auth-Email': email,
            'X-Auth-Key': api_key,
            'Content-Type': 'application/json',
        }
    raise RuntimeError(
        'Cloudflare credential eksik: api_token veya email+api_key (Global API Key) girin.'
    )


def _api_request(method: str, url: str, credentials: dict, payload: dict | None = None) -> dict:
    headers = _auth_headers(credentials)
    body = json.dumps(payload).encode('utf-8') if payload else None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode('utf-8', errors='replace')
        try:
            data = json.loads(raw)
            data['_http_status'] = exc.code
            return data
        except Exception:
            raise RuntimeError(f'Cloudflare HTTP {exc.code}: {raw[:400]}') from exc


class CloudflareProvider(DNSProvider):
    name = 'cloudflare'
    display_name = 'Cloudflare'

    def __init__(self, credentials: dict | None = None):
        super().__init__(credentials)
        self.credentials = normalize_cloudflare_credentials(self.credentials)
        self._zone_id_cache: dict[str, str] = {}

    def is_configured(self) -> bool:
        c = self.credentials
        if (c.get('api_token') or '').strip():
            return True
        email = (c.get('email') or c.get('auth_email') or '').strip()
        api_key = (c.get('api_key') or c.get('global_api_key') or '').strip()
        return bool(email and api_key)

    def _lookup_zone_id(self, zone_name: str) -> str:
        zone_name = zone_name.lower().strip().rstrip('.')
        if zone_name in self._zone_id_cache:
            return self._zone_id_cache[zone_name]

        url = f'{API_BASE}/zones?name={urllib.parse.quote(zone_name)}'
        data = _api_request('GET', url, self.credentials)
        if not data.get('success'):
            raise RuntimeError(f'Cloudflare API hatası: {_format_cf_errors(data)}')
        result = data.get('result') or []
        if not result:
            raise RuntimeError(f'Zone bulunamadı: {zone_name}')
        zone_id = result[0]['id']
        self._zone_id_cache[zone_name] = zone_id
        return zone_id

    def _resolve_zone(self, mail_domain: str) -> tuple[str, str]:
        """
        Mail domain için Cloudflare zone adını bul.

        Örn. mail domain `app.ornek.com` iken zone `ornek.com` olabilir.
        """
        mail_domain = mail_domain.lower().strip().rstrip('.')
        parts = mail_domain.split('.')
        if len(parts) < 2:
            raise RuntimeError(f'Geçersiz domain: {mail_domain}')

        tried: list[str] = []
        last_error = ''
        for i in range(0, len(parts) - 1):
            candidate = '.'.join(parts[i:])
            tried.append(candidate)
            try:
                zone_id = self._lookup_zone_id(candidate)
                return candidate, zone_id
            except Exception as exc:
                last_error = str(exc)

        raise RuntimeError(
            f'Cloudflare zone bulunamadı: {mail_domain}. '
            f'Domain hesabınızda zone olarak ekli olmalı (denenen: {", ".join(tried)}). '
            f'Son hata: {last_error}'
        )

    def _fqdn(self, mail_domain: str, record: DNSRecord) -> str:
        if not record.name or record.name in ('@', ''):
            return mail_domain
        if record.name.endswith('.' + mail_domain) or record.name == mail_domain:
            return record.name
        if record.name.endswith('._domainkey'):
            return f'{record.name}.{mail_domain}'
        return f'{record.name}.{mail_domain}'

    def _semantic_txt_prefix(self, content: str) -> str | None:
        c = (content or '').strip()
        for prefix in ('v=spf1', 'v=DMARC1', 'v=DKIM1'):
            if c.startswith(prefix):
                return prefix
        return None

    def _pick_existing(self, existing: list[dict], record: DNSRecord) -> dict | None:
        if not existing:
            return None
        if record.type != 'TXT':
            return existing[0]
        content = (record.content or '').strip()
        for item in existing:
            item_content = (item.get('content') or '').strip().strip('"')
            if content and item_content == content:
                return item
        prefix = self._semantic_txt_prefix(content)
        if prefix:
            for item in existing:
                if (item.get('content') or '').strip().startswith(prefix):
                    return item
        return existing[0]

    def _delete_record_by_id(self, zone_id: str, cf_zone: str, record_id: str) -> dict:
        url = f'{API_BASE}/zones/{zone_id}/dns_records/{record_id}'
        data = _api_request('DELETE', url, self.credentials)
        if data.get('success'):
            return {'success': True, 'message': 'Kayıt silindi', 'cf_zone': cf_zone}
        return {'success': False, 'message': _format_cf_errors(data), 'cf_zone': cf_zone}

    def _dedupe_conflicting_records(
        self,
        zone_id: str,
        cf_zone: str,
        mail_domain: str,
        record: DNSRecord,
        keep_id: str | None,
    ) -> list[dict]:
        """Çift SPF/DMARC/DKIM veya fazla MX kayıtlarını temizle."""
        existing = self._list_matching(zone_id, mail_domain, record)
        removed: list[dict] = []

        if record.type == 'TXT':
            prefix = self._semantic_txt_prefix(record.content)
            if not prefix:
                return removed
            candidates = [
                item for item in existing
                if (item.get('content') or '').strip().startswith(prefix)
            ]
        elif record.type == 'MX':
            candidates = list(existing)
        else:
            return removed

        for item in candidates:
            rid = item.get('id')
            if not rid or rid == keep_id:
                continue
            outcome = self._delete_record_by_id(zone_id, cf_zone, rid)
            if outcome.get('success'):
                removed.append({
                    'id': rid,
                    'type': record.type,
                    'name': item.get('name') or self._fqdn(mail_domain, record),
                    'action': 'deleted_duplicate',
                })
        return removed

    def _list_matching(self, zone_id: str, mail_domain: str, record: DNSRecord) -> list[dict]:
        name = self._fqdn(mail_domain, record)
        qs = urllib.parse.urlencode({'type': record.type, 'name': name, 'per_page': 50})
        url = f'{API_BASE}/zones/{zone_id}/dns_records?{qs}'
        data = _api_request('GET', url, self.credentials)
        if not data.get('success'):
            return []
        return list(data.get('result') or [])

    def _payload(self, mail_domain: str, record: DNSRecord) -> dict:
        payload: dict = {
            'type': record.type,
            'name': self._fqdn(mail_domain, record),
            'content': record.content,
            'ttl': record.ttl or 3600,
        }
        if record.type in ('A', 'AAAA', 'CNAME'):
            payload['proxied'] = False
        if record.type == 'MX' and record.priority is not None:
            payload['priority'] = record.priority
        return payload

    def verify_mail_domain(self, mail_domain: str) -> dict:
        """Token + zone erişimini test et (panel tanılama)."""
        try:
            cf_zone, zone_id = self._resolve_zone(mail_domain)
            return {
                'success': True,
                'mail_domain': mail_domain,
                'cf_zone': cf_zone,
                'zone_id': zone_id,
            }
        except Exception as exc:
            return {'success': False, 'message': str(exc), 'mail_domain': mail_domain}

    def create_record(self, zone: str, record: DNSRecord) -> dict:
        return self.ensure_record(zone, record)

    def ensure_record(self, zone: str, record: DNSRecord) -> dict:
        """zone = mail domain (paneldeki domain adı)."""
        try:
            mail_domain = zone.lower().strip().rstrip('.')
            cf_zone, zone_id = self._resolve_zone(mail_domain)
            payload = self._payload(mail_domain, record)
            existing = self._list_matching(zone_id, mail_domain, record)
            removed_duplicates: list[dict] = []

            for item in existing:
                same_content = (item.get('content') or '').strip() == (record.content or '').strip()
                same_prio = True
                if record.type == 'MX':
                    same_prio = int(item.get('priority') or 0) == int(record.priority or 0)
                if same_content and same_prio:
                    removed_duplicates = self._dedupe_conflicting_records(
                        zone_id, cf_zone, mail_domain, record, item.get('id'),
                    )
                    msg = 'Kayıt zaten güncel'
                    if removed_duplicates:
                        msg += f' ({len(removed_duplicates)} çift kayıt silindi)'
                    return {
                        'success': True,
                        'id': item.get('id'),
                        'message': msg,
                        'action': 'unchanged',
                        'cf_zone': cf_zone,
                        'removed_duplicates': removed_duplicates,
                    }

            target = self._pick_existing(existing, record)
            if target:
                rid = target['id']
                url = f'{API_BASE}/zones/{zone_id}/dns_records/{rid}'
                data = _api_request('PUT', url, self.credentials, payload)
                if data.get('success'):
                    removed_duplicates = self._dedupe_conflicting_records(
                        zone_id, cf_zone, mail_domain, record, rid,
                    )
                    msg = 'Kayıt güncellendi'
                    if removed_duplicates:
                        msg += f' ({len(removed_duplicates)} çift kayıt silindi)'
                    return {
                        'success': True,
                        'id': rid,
                        'message': msg,
                        'action': 'updated',
                        'cf_zone': cf_zone,
                        'removed_duplicates': removed_duplicates,
                    }
                return {'success': False, 'message': _format_cf_errors(data), 'cf_zone': cf_zone}

            url = f'{API_BASE}/zones/{zone_id}/dns_records'
            data = _api_request('POST', url, self.credentials, payload)
            if data.get('success'):
                rid = (data.get('result') or {}).get('id')
                removed_duplicates = self._dedupe_conflicting_records(
                    zone_id, cf_zone, mail_domain, record, rid,
                )
                msg = 'Kayıt eklendi'
                if removed_duplicates:
                    msg += f' ({len(removed_duplicates)} çift kayıt silindi)'
                return {
                    'success': True,
                    'id': rid,
                    'message': msg,
                    'action': 'created',
                    'cf_zone': cf_zone,
                    'removed_duplicates': removed_duplicates,
                }
            return {'success': False, 'message': _format_cf_errors(data), 'cf_zone': cf_zone}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}

    def delete_record(self, zone: str, record_id: str) -> dict:
        try:
            cf_zone, zone_id = self._resolve_zone(zone)
            url = f'{API_BASE}/zones/{zone_id}/dns_records/{record_id}'
            data = _api_request('DELETE', url, self.credentials)
            if data.get('success'):
                return {'success': True, 'message': 'Kayıt silindi', 'cf_zone': cf_zone}
            return {'success': False, 'message': _format_cf_errors(data)}
        except Exception as exc:
            return {'success': False, 'message': str(exc)}
