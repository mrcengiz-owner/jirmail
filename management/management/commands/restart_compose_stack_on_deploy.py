"""Deploy sonrası tüm compose servislerini yeniden başlat (entrypoint'ten çağrılır)."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from management.stack_restart import restart_compose_stack


class Command(BaseCommand):
    help = 'Dokploy/Compose deploy sonrası postfix, dovecot, celery, redis, postgres yeniden başlat'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--skip-postgres', action='store_true')
        parser.add_argument('--quiet', action='store_true')

    def handle(self, *args, **options):
        report = restart_compose_stack(include_postgres=not options['skip_postgres'])

        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return

        if report.get('skipped'):
            if not options['quiet']:
                self.stdout.write(f"Stack restart atlandı: {report.get('reason', '')}")
            return

        if not options['quiet']:
            self.stdout.write(self.style.MIGRATE_HEADING('Deploy: stack servisleri yeniden başlatılıyor'))
            for item in report.get('restarted', []):
                mark = '✓' if item.get('ok') else '✗'
                msg = item.get('message', '')
                name = item.get('container') or item.get('service', '')
                self.stdout.write(f'  {mark} {name}: {msg}')

        if not report.get('ok'):
            self.stderr.write(self.style.WARNING('Bazı servisler yeniden başlatılamadı (deploy devam ediyor)'))
