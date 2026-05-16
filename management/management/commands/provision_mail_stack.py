"""Postfix + Dovecot: compose üret veya Docker ile kur (HARİCİ Postgres)."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from installer.mail_stack import (
    mail_stack_instructions_markdown,
    mail_stack_params_from_env,
    provision_mail_stack_docker,
    render_mail_stack_compose_yaml,
)


class Command(BaseCommand):
    help = (
        'Harici PostgreSQL (DATABASE_URL) ile Postfix+Dovecot kurar veya Coolify için compose YAML yazdırır. '
        'Coolify panel konteynerinde Docker soketi yoksa yalnızca YAML üretilir.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--print-compose',
            action='store_true',
            help='Sadece docker-compose YAML yazdır (dosyaya yönlendirin: > mail-stack.yml)',
        )
        parser.add_argument(
            '--apply-docker',
            action='store_true',
            help='Docker API erişilebiliyorsa konteynerleri oluşturur/yeniler (dikkat: prod)',
        )
        parser.add_argument(
            '--no-pull',
            action='store_true',
            help='--apply-docker ile image pull yapma',
        )
        parser.add_argument(
            '--json',
            action='store_true',
            help='JSON çıktı (--apply-docker sonucu)',
        )

    def handle(self, *args, **options):
        if options['print_compose']:
            try:
                p = mail_stack_params_from_env()
            except Exception as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(render_mail_stack_compose_yaml(p))
            self.stdout.write('\n# --- Not ---\n')
            self.stdout.write(mail_stack_instructions_markdown())
            return

        if options['apply_docker']:
            result = provision_mail_stack_docker(
                skip_busy_ports=True,
                pull_images=not options['no_pull'],
            )
            if options['json']:
                self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                for line in result.get('messages') or []:
                    self.stdout.write(line)
                if result.get('compose_yaml') and not result.get('success'):
                    self.stdout.write(self.style.WARNING('\n--- compose.yaml (yedek) ---\n'))
                    self.stdout.write(result['compose_yaml'])
                if result.get('error'):
                    self.stdout.write(self.style.ERROR(result['error']))
                if result.get('success'):
                    self.stdout.write(self.style.SUCCESS('\nTamamlandı.'))
                elif result.get('mode') == 'no_docker':
                    self.stdout.write(
                        self.style.WARNING(
                            '\nDocker yok — `python manage.py provision_mail_stack --print-compose` '
                            'ile YAML alıp Coolify’da deploy edin.'
                        )
                    )
            if not result.get('success') and result.get('mode') != 'no_docker':
                raise CommandError(result.get('error') or 'Kurulum başarısız.')
            return

        self.stdout.write(self.style.MIGRATE_HEADING('Postfix + Dovecot altyapısı'))
        self.stdout.write('')
        self.stdout.write('  --print-compose   Coolify / compose için YAML üret')
        self.stdout.write('  --apply-docker    Sunucuda Docker soketi varsa konteyner kur')
        self.stdout.write('')
        self.stdout.write('Ortam: DATABASE_URL (zorunlu), MAIL_DOMAIN, MAIL_STACK_DOCKER_NETWORK (Coolify ağı)')
        self.stdout.write(mail_stack_instructions_markdown())
