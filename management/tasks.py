"""Periyodik mail stack bakım görevleri."""
from celery import shared_task


@shared_task(name='management.auto_heal_mail_stack')
def auto_heal_mail_stack():
    """Postfix pgsql + Dovecot yapılandırmasını doğrula ve gerekirse onar."""
    from management.mail_stack_health import verify_mail_stack

    return verify_mail_stack(fix=True)
