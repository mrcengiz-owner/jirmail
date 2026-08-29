"""System DNS config ve domain otomasyon testleri."""
from django.test import TestCase
from unittest.mock import patch

from core.models import MailDomain
from dns_providers.system_dns import auto_apply_domain_dns, get_system_dns_config, persist_system_dns_config
from saas.models import SystemConfig


class SystemDnsConfigTests(TestCase):
    def test_get_system_dns_from_config(self):
        SystemConfig.objects.create(
            is_installed=True,
            dns_provider='cloudflare',
            dns_credentials={'api_token': 'test-token-abc'},
        )
        provider, creds = get_system_dns_config(persist_fallback=False)
        self.assertEqual(provider, 'cloudflare')
        self.assertEqual(creds.get('api_token'), 'test-token-abc')

    def test_persist_and_read_roundtrip(self):
        cfg = SystemConfig.objects.create(is_installed=True)
        persist_system_dns_config('cloudflare', {'api_token': 'roundtrip-token'})
        cfg.refresh_from_db()
        self.assertEqual(cfg.dns_provider, 'cloudflare')
        self.assertEqual(cfg.dns_credentials.get('api_token'), 'roundtrip-token')

    @patch('dns_providers.records.apply_mail_dns')
    def test_auto_apply_on_new_domain(self, mock_apply):
        SystemConfig.objects.create(
            is_installed=True,
            dns_provider='cloudflare',
            dns_credentials={'api_token': 'cf-token'},
        )
        mock_apply.return_value = {
            'success': True,
            'skipped': False,
            'created': 6,
            'total': 6,
            'results': [],
        }
        domain = MailDomain.objects.create(name='yeni.com', is_active=True)
        outcome = auto_apply_domain_dns(domain)
        self.assertTrue(outcome.get('applied'))
        self.assertTrue(outcome.get('success'))
        mock_apply.assert_called_once()
        domain.refresh_from_db()
        self.assertTrue(domain.dkim_record)
        self.assertEqual(domain.dns_provider, 'cloudflare')

    def test_auto_apply_skips_manual(self):
        SystemConfig.objects.create(is_installed=True, dns_provider='manual')
        domain = MailDomain.objects.create(name='manuel.com', is_active=True)
        outcome = auto_apply_domain_dns(domain)
        self.assertFalse(outcome.get('applied'))
        self.assertTrue(outcome.get('skipped'))
        domain.refresh_from_db()
        self.assertTrue(domain.dkim_record)
