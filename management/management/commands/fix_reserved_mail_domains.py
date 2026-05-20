"""Panelde yanlış eklenmiş harici domainleri (proton.me vb.) pasifleştirir."""
from django.core.management.base import BaseCommand

from core.mail_domains import is_reserved_public_domain, normalize_domain
from core.models import MailDomain
from management.postfix_maps import reload_virtual_mailboxes


class Command(BaseCommand):
    help = 'Gmail/Proton gibi harici domainleri MailDomain listesinden pasifleştirir (Postfix LMTP hatası).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Yalnızca listele, değiştirme.',
        )

    def handle(self, *args, **options):
        dry = options['dry_run']
        qs = MailDomain.objects.filter(is_active=True)
        fixed = []
        for dom in qs:
            name = normalize_domain(dom.name)
            if not is_reserved_public_domain(name):
                continue
            fixed.append(name)
            if dry:
                self.stdout.write(f'[dry-run] pasifleştirilecek: {name}')
            else:
                dom.is_active = False
                dom.save(update_fields=['is_active'])
                self.stdout.write(self.style.WARNING(f'Pasifleştirildi: {name}'))

        if not fixed:
            self.stdout.write(self.style.SUCCESS('Yanlış yapılandırılmış domain yok.'))
            return

        if dry:
            self.stdout.write('Uygulamak için --dry-run olmadan tekrar çalıştırın.')
            return

        reload_virtual_mailboxes()
        self.stdout.write(
            self.style.SUCCESS(
                f'{len(fixed)} domain pasifleştirildi. Postfix yenilendi. '
                'Gerekirse: docker exec jir_postfix sh /docker-init.d/31-jirmail-transport-maps.sh'
            )
        )
