"""SMTP üzerinden test maili gönderir."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.models import MailAccount
from webmail.smtp_client import send_mail


class Command(BaseCommand):
    help = 'Belirtilen adrese SMTP submission ile test maili gönderir.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--to',
            default='mracengiz@gmail.com',
            help='Alıcı e-posta (varsayılan: mracengiz@gmail.com)',
        )
        parser.add_argument(
            '--from-email',
            dest='from_email',
            help='Gönderen MailAccount e-postası (belirtilmezse ilk aktif hesap)',
        )
        parser.add_argument(
            '--password',
            required=True,
            help='Gönderen hesabın düz metin parolası (SMTP AUTH)',
        )
        parser.add_argument(
            '--subject',
            default='JîrCode Webmail Test',
            help='Mail konusu',
        )

    def handle(self, *args, **options):
        to_addr = options['to'].strip()
        password = options['password']
        subject = options['subject']

        qs = MailAccount.objects.filter(is_active=True).select_related('domain')
        if options['from_email']:
            account = qs.filter(email__iexact=options['from_email'].strip()).first()
        else:
            account = qs.order_by('id').first()

        if not account:
            raise CommandError('Aktif MailAccount bulunamadı. --from-email ile hesap belirtin.')

        body = (
            f'Bu mesaj JîrCode webmail test komutu ile gönderildi.\n\n'
            f'Gönderen: {account.email}\n'
            f'Alıcı: {to_addr}\n'
        )

        self.stdout.write(f'Gönderen: {account.email} → {to_addr}')

        result = send_mail(
            account,
            password,
            to=to_addr,
            subject=subject,
            body_text=body,
        )

        if result.get('success'):
            self.stdout.write(self.style.SUCCESS(
                f'Mail gönderildi. Message-ID: {result.get("message_id", "—")}'
            ))
            return

        raise CommandError(result.get('message', 'Gönderim başarısız.'))
