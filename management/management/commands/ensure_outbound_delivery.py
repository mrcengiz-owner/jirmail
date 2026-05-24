"""Dış posta çıkışını otomatik yapılandır."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from management.outbound_autoconfig import ensure_outbound_delivery


class Command(BaseCommand):
    help = 'Port 25 / relay / transport maps otomatik yapılandır (deploy ve gönderim öncesi)'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument('--no-fix', action='store_true', help='Yalnızca kontrol et')
        parser.add_argument('--force', action='store_true', help='Önbelleği atla')
        parser.add_argument(
            '--full-heal',
            action='store_true',
            help='Postfix init script\'lerini çalıştır (yavaş)',
        )

    def handle(self, *args, **options):
        report = ensure_outbound_delivery(
            fix=not options['no_fix'],
            force=options['force'],
            full_heal=options['full_heal'],
        )
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2, default=str))
            return

        mode = report.get('mode', '?')
        msg = report.get('message') or ''
        if report.get('ok'):
            self.stdout.write(self.style.SUCCESS(f'Outbound: {mode} — {msg}'))
        else:
            self.stdout.write(self.style.WARNING(f'Outbound: {mode} — {msg}'))

        for dom in report.get('fixed_domains') or []:
            self.stdout.write(self.style.WARNING(f'  Pasifleştirildi: {dom}'))
