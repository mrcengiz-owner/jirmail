"""Deploy / Coolify ortam kontrolü — `python manage.py check_deploy`"""
from __future__ import annotations

import json
import sys

from django.core.management.base import BaseCommand

from management.deploy_readiness import CHECK_ERR, collect_deploy_readiness


class Command(BaseCommand):
    help = 'Coolify/PaaS deploy uyumluluk kontrolü (veritabanı, Docker, mail, profil).'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='JSON çıktı')
        parser.add_argument(
            '--fail-on-error',
            action='store_true',
            help='status=error ise çıkış kodu 1',
        )

    def handle(self, *args, **options):
        report = collect_deploy_readiness()
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(self.style.MIGRATE_HEADING('Jîr-Mail deploy kontrolü'))
            self.stdout.write(f"Durum: {report['status'].upper()}\n")
            for line in report.get('summary_lines', []):
                self.stdout.write(f'  • {line}')
            self.stdout.write('')
            for chk in report.get('checks', []):
                st = chk['status']
                style = self.style.SUCCESS
                if st == 'warning':
                    style = self.style.WARNING
                elif st == 'error':
                    style = self.style.ERROR
                self.stdout.write(style(f"[{st}] {chk['title']}: {chk['message']}"))
                if chk.get('hint'):
                    self.stdout.write(f"       → {chk['hint']}")
        if options['fail_on_error'] and report.get('status') == CHECK_ERR:
            sys.exit(1)
