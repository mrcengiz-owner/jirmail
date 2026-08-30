"""Cloudflare çift SPF/DMARC temizleme testleri."""
from unittest.mock import patch

from django.test import SimpleTestCase

from dns_providers.base import DNSRecord
from dns_providers.cloudflare import CloudflareProvider


class CloudflareDedupeTests(SimpleTestCase):
    def setUp(self):
        self.provider = CloudflareProvider({'api_token': 'test-token'})

    @patch.object(CloudflareProvider, '_resolve_zone', return_value=('mrcengiz.com', 'zone123'))
    @patch.object(CloudflareProvider, '_list_matching')
    @patch('dns_providers.cloudflare._api_request')
    def test_ensure_record_removes_duplicate_spf(self, mock_api, mock_list, _mock_zone):
        mock_list.return_value = [
            {'id': 'spf-old', 'content': 'v=spf1 mx a:old -all', 'name': 'mrcengiz.com'},
            {'id': 'spf-new', 'content': 'v=spf1 mx a:mail.jircode.com -all', 'name': 'mrcengiz.com'},
        ]
        mock_api.side_effect = [
            {'success': True, 'result': {'id': 'spf-new'}},  # PUT update
            {'success': True},  # DELETE spf-old
        ]

        record = DNSRecord(name='@', type='TXT', content='v=spf1 mx a:mail.jircode.com -all')
        outcome = self.provider.ensure_record('mrcengiz.com', record)

        self.assertTrue(outcome.get('success'))
        self.assertEqual(outcome.get('action'), 'updated')
        self.assertEqual(len(outcome.get('removed_duplicates') or []), 1)
        delete_calls = [c for c in mock_api.call_args_list if c[0][0] == 'DELETE']
        self.assertEqual(len(delete_calls), 1)
