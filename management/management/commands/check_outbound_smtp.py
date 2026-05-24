"""Dış posta — port 25 ve relayhost tanılama."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from management.outbound_connectivity import check_outbound_smtp
from webmail.send_validation import admin_panel_domain_issues


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
        issues = admin_panel_domain_issues()
        stale = [i['message'] for i in issues]

        if options['json']:
            out = {**report, 'panel_warnings': stale, 'panel_issues': issues}
            self.stdout.write(json.dumps(out, ensure_ascii=False, indent=2))
            return

        if issues:
            self.stdout.write(self.style.WARNING('Panel (gönderimi engellemez — yapılandırma notu):'))
            for item in issues[:8]:
                self.stdout.write(f"  • {item['message']}")
                self.stdout.write(f"    → {item['fix']}")
            self.stdout.write('')

        mode = report.get('mode', '')
        if mode == 'relay':
            self.stdout.write(self.style.SUCCESS(f"Mod: RELAY — {report.get('relayhost')}"))
            self.stdout.write(report.get('message', ''))
            return

        self.stdout.write(self.style.MIGRATE_HEADING('Mod: doğrudan internet SMTP (port 25)'))
        self.stdout.write(report.get('message', ''))
        summary = report.get('probe_summary') or {}
        if summary.get('postfix_total'):
            ok_n = summary.get('postfix_ok', 0)
            total = summary['postfix_total']
            if ok_n < total and report.get('ok'):
                self.stdout.write(
                    self.style.NOTICE(
                        f'Not: {ok_n}/{total} Postfix hedefi yanıt verdi — en az biri OK ise gönderim yapılabilir.'
                    )
                )
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
