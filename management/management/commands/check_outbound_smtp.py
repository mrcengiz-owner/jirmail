"""Dış posta — port 25 ve relayhost tanılama."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from management.outbound_connectivity import check_outbound_smtp
from webmail.send_validation import admin_stale_domain_warnings


class Command(BaseCommand):
    help = 'Postfix konteynerinden MX port 25 erişimini ve relayhost ayarını kontrol eder'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='JSON çıktı')
        parser.add_argument(
            '--skip-panel-probe',
            action='store_true',
            help='Django konteynerinden ek TCP testi yapma',
        )

    def handle(self, *args, **options):
        report = check_outbound_smtp(include_django_probe=not options['skip_panel_probe'])
        stale = admin_stale_domain_warnings()

        if options['json']:
            out = {**report, 'panel_warnings': stale}
            self.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
            return

        if stale:
            self.stdout.write(self.style.WARNING('Panel (isteğe bağlı temizlik):'))
            for w in stale[:5]:
                self.stdout.write(f'  • {w}')
            self.stdout.write('  → python manage.py fix_reserved_mail_domains\n')

        mode = report.get('mode', '')
        if mode == 'relay':
            self.stdout.write(self.style.SUCCESS(f"Mod: RELAY — {report.get('relayhost')}"))
            self.stdout.write(report.get('message', ''))
            return

        self.stdout.write(self.style.MIGRATE_HEADING('Mod: doğrudan internet SMTP (port 25)'))
        self.stdout.write(report.get('message', ''))
        self.stdout.write('')

        for p in report.get('probes') or []:
            mark = '✓' if p.get('from_postfix') else '✗'
            line = f"  {mark} {p.get('target')} ({p.get('host')}:{p.get('port')}) — Postfix: {p.get('postfix_message')}"
            if p.get('from_panel') is not None:
                line += f" | Panel: {'OK' if p.get('from_panel') else 'kapalı'}"
            self.stdout.write(line)

        if report.get('recommendation'):
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(report['recommendation']))

        if not report.get('ok'):
            self.stdout.write('')
            self.stdout.write('Hızlı test (sunucuda):')
            self.stdout.write(
                '  docker exec jir_postfix timeout 6 bash -c '
                '"echo >/dev/tcp/gmail-smtp-in.l.google.com/25" && echo OK || echo FAIL'
            )
            self.stdout.write('  docker exec jir_postfix postconf -h relayhost')
