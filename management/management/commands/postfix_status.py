"""Postfix konteyner durumu ve hızlı kurtarma."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Postfix çalışıyor mu, pgsql map ve submission portu kontrolü'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true')
        parser.add_argument(
            '--fix-maps',
            action='store_true',
            help='pgsql map init script\'lerini çalıştır (postfix çalışmasa da)',
        )

    def handle(self, *args, **options):
        from management.outbound_autoconfig import apply_postfix_outbound_scripts

        report: dict = {'ok': False, 'postfix_running': False, 'checks': [], 'actions': []}

        def add(cid: str, ok: bool, msg: str):
            report['checks'].append({'id': cid, 'ok': ok, 'message': msg})

        name = __import__('os').environ.get('JIR_CONTAINER_POSTFIX', 'jir_postfix')

        try:
            import docker
            from django.conf import settings

            client = docker.DockerClient(
                base_url=getattr(settings, 'DOCKER_HOST', None) or 'unix:///var/run/docker.sock',
                timeout=20,
            )
            c = client.containers.get(name)
            report['container'] = name
            report['container_status'] = c.status

            if options['fix_maps']:
                for script in (
                    '/docker-init.d/10-jirmail-inbound.sh',
                    '/docker-init.d/31-jirmail-transport-maps.sh',
                    '/docker-init.d/11-validate-pgsql.sh',
                ):
                    code, logs = c.exec_run(['sh', script], demux=True)
                    out = ((logs[0] or b'') + (logs[1] or b'')).decode()[:400]
                    report['actions'].append({'script': script, 'exit_code': code, 'output': out})

            code, logs = c.exec_run(['postfix', 'status'], demux=True)
            stdout = ((logs[0] or b'') + (logs[1] or b'')).decode().strip()
            running = code == 0 and 'is running' in stdout.lower()
            report['postfix_running'] = running
            add('postfix_status', running, stdout or f'exit {code}')

            code, logs = c.exec_run(['postconf', '-h', 'daemon_directory'], demux=True)
            dd = (logs[0] or b'').decode().strip()
            add('postconf', bool(dd), f'daemon_directory={dd or "(boş — pgsql map hatası)"}')

            for cf in (
                'pgsql-virtual-mailboxes.cf',
                'pgsql-virtual-domains.cf',
                'pgsql-transport-maps.cf',
            ):
                code, logs = c.exec_run(['grep', '-E', '^port = |^dbname = ', f'/etc/postfix/{cf}'], demux=True)
                lines = (logs[0] or b'').decode().strip()
                bad_port = 'port = ' in lines
                has_db = 'dbname = ' in lines
                add(f'cf_{cf}', has_db and not bad_port, lines or '(dosya yok)')

            client.close()
        except Exception as exc:
            add('docker', False, str(exc))
            report['error'] = str(exc)

        report['ok'] = report.get('postfix_running') and all(
            x.get('ok') for x in report['checks'] if x['id'] in ('postfix_status', 'postconf')
        )

        if options['json']:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
            return

        if report.get('postfix_running'):
            self.stdout.write(self.style.SUCCESS(f'Postfix çalışıyor ({name})'))
        else:
            self.stdout.write(self.style.ERROR(f'Postfix ÇALIŞMIYOR ({name})'))
            self.stdout.write('  → docker restart jir_postfix')
            self.stdout.write('  → docker logs jir_postfix --tail 60')

        for chk in report.get('checks', []):
            mark = '✓' if chk.get('ok') else '✗'
            self.stdout.write(f"  {mark} {chk['id']}: {chk['message'][:120]}")

        if not report.get('postfix_running'):
            self.stdout.write('')
            self.stdout.write(
                self.style.WARNING(
                    'Manuel init script çalıştırmak postfix\'i başlatmaz — konteyneri yeniden başlatın.'
                )
            )
