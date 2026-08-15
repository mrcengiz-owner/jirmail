import os
import sys

sys.path.insert(0, str(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.test import TestCase, Client
from core.models import MailAccount, MailDomain
from saas.models import SystemConfig, Alert, AlertThreshold
import bcrypt


class TestManagementAPI(TestCase):
    fixtures = []

    def setUp(self):
        self.client = Client()

    def test_health_check(self):
        response = self.client.get('/api/management/health')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('status', data)
        self.assertIn('database', data)

    def test_login_success(self):
        domain = MailDomain.objects.create(name='testdomain.com')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw('testpass123'.encode('utf-8'), salt).decode('utf-8')
        account = MailAccount.objects.create(
            domain=domain, username='admin', email='admin@testdomain.com',
            password_hash=hashed, role='FULL'
        )
        response = self.client.post(
            '/api/management/login',
            data='{"email":"admin@testdomain.com","password":"testpass123"}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')

    def test_login_invalid_password(self):
        domain = MailDomain.objects.create(name='testdomain2.com')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw('testpass123'.encode('utf-8'), salt).decode('utf-8')
        account = MailAccount.objects.create(
            domain=domain, username='admin', email='admin@testdomain2.com',
            password_hash=hashed, role='FULL'
        )
        response = self.client.post(
            '/api/management/login',
            data='{"email":"admin@testdomain2.com","password":"wrongpassword"}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'error')

    def test_login_nonexistent_account(self):
        response = self.client.post(
            '/api/management/login',
            data='{"email":"nonexistent@testdomain.com","password":"anypassword"}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'error')

    def test_system_specs_unauthorized(self):
        response = self.client.get('/api/management/system-specs')
        self.assertIn(response.status_code, (200, 403))
        data = response.json()
        self.assertEqual(data.get('status'), 'error')

    def test_system_requirements_unauthorized(self):
        response = self.client.get('/api/management/system-requirements')
        self.assertIn(response.status_code, (200, 403))
        data = response.json()
        self.assertEqual(data.get('status'), 'error')


class TestCoreAPI(TestCase):
    def setUp(self):
        self.client = Client()
        self.config = SystemConfig.objects.create(
            is_installed=True,
            jir_local_key='TestKey_12345',
            tier='PRO',
            max_accounts=50
        )
        self.domain = MailDomain.objects.create(name='testdomain.com')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw('testpass123'.encode('utf-8'), salt).decode('utf-8')
        self.account = MailAccount.objects.create(
            domain=self.domain, username='admin', email='admin@testdomain.com',
            password_hash=hashed, role='FULL'
        )


    def test_create_account_unauthorized(self):
        response = self.client.post(
            '/api/core/create-account',
            data='{"username":"x","domain":"testdomain.com","password":"pass12345"}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'error')

    def test_create_account_with_service_header(self):
        response = self.client.post(
            '/api/core/create-account',
            data='{"username":"newbie","domain":"testdomain.com","password":"pass12345"}',
            content_type='application/json',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')

    def test_query_key_no_longer_works(self):
        response = self.client.get(f'/api/core/list-accounts?key={self.config.jir_local_key}')
        data = response.json()
        self.assertEqual(data.get('status'), 'error')

    def test_list_accounts_unauthorized(self):
        response = self.client.get('/api/core/list-accounts?key=wrongkey')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'error')

    def test_list_accounts_authorized(self):
        response = self.client.get('/api/core/list-accounts', HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('accounts', data)

    def test_list_domains(self):
        response = self.client.get('/api/core/list-domains', HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('domains', data)

    def test_generate_dns_records(self):
        response = self.client.post(
            f'/api/core/generate-dns-records/{self.domain.name}',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('spf_record', data)
        self.assertIn('dkim_record', data)

    def test_add_domain(self):
        response = self.client.post(
            '/api/core/add-domain',
            data='{"name":"newdomain.com","is_active":true}',
            content_type='application/json',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')

    def test_toggle_domain(self):
        original_status = self.domain.is_active
        response = self.client.patch(
            f'/api/core/toggle-domain/{self.domain.name}',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.domain.refresh_from_db()
        self.assertEqual(self.domain.is_active, not original_status)


class TestAlertsAPI(TestCase):
    def setUp(self):
        self.client = Client()

    def test_get_alerts_unauthorized(self):
        response = self.client.get('/api/alerts/alerts')
        self.assertEqual(response.status_code, 403)

    def test_get_metrics_unauthorized(self):
        response = self.client.get('/api/alerts/metrics')
        self.assertEqual(response.status_code, 403)

    def test_resolve_all_alerts_unauthorized(self):
        response = self.client.post('/api/alerts/alerts/resolve-all')
        self.assertEqual(response.status_code, 403)

    def test_mark_all_read_unauthorized(self):
        response = self.client.post('/api/alerts/mark-all-read')
        self.assertEqual(response.status_code, 403)


class TestBackupAPI(TestCase):
    def setUp(self):
        self.client = Client()

    def test_list_backups_unauthorized(self):
        response = self.client.get('/api/backup/list-backups')
        self.assertEqual(response.status_code, 403)

    def test_create_backup_unauthorized(self):
        response = self.client.post(
            '/api/backup/create-backup',
            data='{"backup_type":"full","include_emails":false,"include_configs":true,"include_database":true}',
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)


class TestEmailSettings(TestCase):
    def setUp(self):
        self.client = Client()
        self.config = SystemConfig.objects.create(
            is_installed=True,
            jir_local_key='TestKey_12345',
            tier='PRO',
            max_accounts=50
        )
        self.domain = MailDomain.objects.create(name='testdomain.com')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw('testpass123'.encode('utf-8'), salt).decode('utf-8')
        self.account = MailAccount.objects.create(
            domain=self.domain, username='admin', email='admin@testdomain.com',
            password_hash=hashed, role='FULL'
        )

    def test_get_email_settings(self):
        response = self.client.get(
            f'/api/core/account-settings/{self.account.email}',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertIn('settings', data)

    def test_update_email_settings(self):
        response = self.client.patch(
            f'/api/core/update-settings/{self.account.email}',
            data='{"signature":"Test Signature","auto_responder_enabled":true,"auto_responder_subject":"Out of Office","auto_responder_body":"I am currently unavailable"}',
            content_type='application/json',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')


class TestAccountManagement(TestCase):
    def setUp(self):
        self.client = Client()
        self.config = SystemConfig.objects.create(
            is_installed=True,
            jir_local_key='TestKey_12345',
            tier='PRO',
            max_accounts=50
        )
        self.domain = MailDomain.objects.create(name='testdomain.com')
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw('testpass123'.encode('utf-8'), salt).decode('utf-8')
        self.account = MailAccount.objects.create(
            domain=self.domain, username='admin', email='admin@testdomain.com',
            password_hash=hashed, role='FULL'
        )

    def test_get_account_details(self):
        response = self.client.get(
            f'/api/core/account-details/{self.account.email}',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data['account']['email'], self.account.email)

    def test_toggle_account(self):
        original_status = self.account.is_active
        response = self.client.patch(
            f'/api/core/toggle-account/{self.account.email}',
            HTTP_X_JIR_LOCAL_KEY=self.config.jir_local_key,
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data.get('status'), 'success')
        self.account.refresh_from_db()
        self.assertEqual(self.account.is_active, not original_status)


if __name__ == '__main__':
    import unittest
    unittest.main()