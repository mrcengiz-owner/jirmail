"""Compose stack: dahili mail PKI dosyalarını volume'a yaz."""
from django.core.management.base import BaseCommand

from installer.mail_pki import MAIL_TLS_MOUNT, ensure_mail_pki_files


class Command(BaseCommand):
    help = 'Dahili mail TLS sertifikalarını oluşturur (Docker Compose volume).'

    def add_arguments(self, parser):
        parser.add_argument('--domain', default='', help='Mail domain (örn. jircode.com)')
        parser.add_argument('--hostname', default='', help='Mail hostname (örn. mail.jircode.com)')
        parser.add_argument('--force', action='store_true', help='Mevcut sertifikayı yeniden üret')

    def handle(self, *args, **options):
        import os
        from pathlib import Path

        domain = (options['domain'] or os.getenv('MAIL_DOMAIN') or 'mail.local').strip()
        hostname = (options['hostname'] or os.getenv('MAIL_HOSTNAME') or f'mail.{domain}').strip()
        tls_dir = Path(MAIL_TLS_MOUNT)
        material = ensure_mail_pki_files(
            tls_dir,
            mail_hostname=hostname,
            mail_domain=domain,
            postfix_host=os.getenv('SMTP_HOST', 'postfix'),
            dovecot_host=os.getenv('IMAP_HOST', 'dovecot'),
            force=bool(options['force']),
        )
        self.stdout.write(self.style.SUCCESS(f'PKI hazır: {tls_dir} ({len(material.ca_cert_pem)} byte CA)'))
