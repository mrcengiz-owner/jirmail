"""Tüm aktif hesaplar için maildir + Postfix pgsql eşlemesi."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Aktif mail hesapları için Maildir oluşturur ve Postfix yapılandırmasını yeniler'

    def handle(self, *args, **options):
        from core.mail_provision import provision_all_active_accounts

        result = provision_all_active_accounts()
        self.stdout.write(
            self.style.SUCCESS(
                f"Tamam: {result['provisioned']} hesap hazırlandı (Postfix Postgres haritası canlı)."
            )
        )
