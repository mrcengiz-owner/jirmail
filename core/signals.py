"""Mail hesabı / domain değişince otomatik maildir + postfix."""
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from core.models import MailAccount, MailDomain


@receiver(post_save, sender=MailAccount)
def mail_account_saved(sender, instance: MailAccount, **kwargs):
    if instance.is_active:
        from core.mail_provision import provision_mail_account

        try:
            provision_mail_account(instance)
        except Exception:
            pass


@receiver(post_delete, sender=MailAccount)
def mail_account_deleted(sender, instance: MailAccount, **kwargs):
    from core.mail_provision import reload_postfix

    try:
        reload_postfix()
    except Exception:
        pass


@receiver(post_save, sender=MailDomain)
def mail_domain_saved(sender, instance: MailDomain, **kwargs):
    if instance.is_active:
        from core.mail_provision import reload_postfix

        try:
            reload_postfix()
        except Exception:
            pass
