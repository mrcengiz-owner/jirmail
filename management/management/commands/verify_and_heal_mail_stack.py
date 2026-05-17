"""Otomatik mail stack doğrulama ve onarım — deploy/entrypoint/cron."""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from management.mail_stack_health import run_mail_stack_self_test, verify_mail_stack


class Command(BaseCommand):
    help = 'Postfix pgsql + Dovecot + SMTP/IMAP doğrula; --fix ile Docker üzerinden onar'

    def add_arguments(self, parser):
        parser.add_argument('--fix', action='store_true', help='Bozuk yapılandırmayı onar')
        parser.add_argument('--json', action='store_true', help='JSON çıktı')
        parser.add_argument('--quiet', action='store_true', help='Sadece hata/özet')
        parser.add_argument('--fail-on-error', action='store_true', help='Başarısızsa çıkış 1')
        parser.add_argument('--self-test-only', action='store_true', help='Yalnızca birim testleri')
        parser.add_argument(
            '--healthcheck',
            action='store_true',
            help='Konteyner healthcheck (hesap yokluğu kritik değil)',
        )

    def handle(self, *args, **options):
        if options['self_test_only']:
            result = run_mail_stack_self_test()
            if options['json']:
                self.stdout.write(json.dumps(result, indent=2))
            elif not options['quiet']:
                self.stdout.write(f"Self-test: {'OK' if result['ok'] else 'FAIL'}")
            if options['fail_on_error'] and not result['ok']:
                sys.exit(1)
            return

        report = verify_mail_stack(fix=options['fix'], healthcheck=options['healthcheck'])

        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        elif not options['quiet']:
            status = 'OK' if report['ok'] else 'HATA'
            self.stdout.write(self.style.MIGRATE_HEADING(f'Mail stack: {status}'))
            for chk in report.get('checks', []):
                mark = '✓' if chk.get('ok') else '✗'
                self.stdout.write(f"  {mark} {chk.get('id')}: {chk.get('message')}")
            for h in report.get('healed', []):
                self.stdout.write(f"  → onarım: {h}")
        elif not report['ok']:
            failed = [c['id'] for c in report.get('checks', []) if not c.get('ok')]
            self.stderr.write(f"Mail stack: {', '.join(failed)}")

        if options['fail_on_error'] and not report['ok']:
            sys.exit(1)
