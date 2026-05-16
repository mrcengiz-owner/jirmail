"""Coolify / Docker üzerinde Postfix ve Dovecot keşfi."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from management.coolify_discovery import collect_full_discovery_report


class Command(BaseCommand):
    help = 'Postfix/Dovecot konteyner keşfi, TCP uçları ve Coolify için önerilen env (Docker API varsa).'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Tam raporu JSON yazdır')

    def handle(self, *args, **options):
        report = collect_full_discovery_report()
        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return

        self.stdout.write(self.style.MIGRATE_HEADING('Postfix / Dovecot keşfi (Coolify dostu)'))
        self.stdout.write('')

        pe = report.get('platform_env') or {}
        if pe:
            self.stdout.write(self.style.HTTP_INFO('Ortam (özet — DATABASE_URL kısaltılmış olabilir):'))
            for k, v in sorted(pe.items()):
                self.stdout.write(f'  {k}={v}')
            self.stdout.write('')
        else:
            self.stdout.write(self.style.WARNING('İlgili ortam değişkeni görünmüyor (Coolify’da panel uygulamasına env ekleyin).'))
            self.stdout.write('')

        m = report.get('merged_container_names') or {}
        self.stdout.write(self.style.HTTP_INFO('Panelin çözdüğü konteyner adları:'))
        self.stdout.write(f'  postfix → {m.get("postfix", "")}')
        self.stdout.write(f'  dovecot → {m.get("dovecot", "")}')
        stored = report.get('stored_docker_container_map') or {}
        if stored:
            self.stdout.write(self.style.WARNING(f'  DB docker_container_map: {stored}'))
        self.stdout.write('')

        inv = report.get('docker_inventory') or {}
        if inv.get('docker_error'):
            self.stdout.write(self.style.ERROR(f'Docker API: {inv["docker_error"]}'))
        elif inv.get('docker_ping'):
            cts = inv.get('containers') or []
            self.stdout.write(self.style.SUCCESS(f'Docker ping OK — {len(cts)} ilgili konteyner'))
            for c in cts:
                nets = c.get('network_ips') or {}
                net_s = ', '.join(f'{n}={ip}' for n, ip in sorted(nets.items())) or '(ağ IP yok)'
                svc = c.get('compose_service') or '-'
                panel_tag = '  [PANEL]' if c.get('is_panel') else ''
                self.stdout.write(
                    f'  • {c.get("name")}{panel_tag}  [{c.get("status")}]  compose:{svc}\n'
                    f'    image: {c.get("image", "")[:100]}\n'
                    f'    networks: {net_s}'
                )
        else:
            self.stdout.write(self.style.WARNING('Docker API yok — listeleme atlandı.'))
        self.stdout.write('')

        mt = report.get('mail_tcp') or {}
        self.stdout.write(self.style.HTTP_INFO('Bu süreçten SMTP/IMAP TCP kontrolü:'))
        for key in ('smtp_submission', 'imap'):
            block = mt.get(key) or {}
            ok = block.get('tcp_ok')
            h, p = block.get('host'), block.get('port')
            st = self.style.SUCCESS('erişilebilir') if ok else self.style.ERROR('erişilemiyor')
            self.stdout.write(f'  {key}: {h}:{p} — {st}')
        self.stdout.write('')

        hint = report.get('network_overlap_hint') or ''
        if hint:
            self.stdout.write(self.style.WARNING(f'Ağ notu: {hint}'))
            self.stdout.write('')

        conn = report.get('network_connectivity') or {}
        fixes = conn.get('recommended_fixes') or []
        if fixes:
            self.stdout.write(self.style.MIGRATE_HEADING('Önerilen düzeltmeler:'))
            for i, line in enumerate(fixes, 1):
                self.stdout.write(f'  {i}. {line}')
            self.stdout.write('')

        self.stdout.write(self.style.HTTP_INFO('Coolify için örnek env (kopyala — gerçek konteyner adlarını listeden seç):'))
        self.stdout.write(report.get('suggested_env_snippet') or '')
        self.stdout.write('')
        self.stdout.write('Tam JSON: python manage.py discover_mail_services --json')
