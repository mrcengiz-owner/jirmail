"""Periyodik mail stack bakım görevleri."""
from celery import shared_task


@shared_task(name='management.auto_heal_mail_stack')
def auto_heal_mail_stack():
    """Postfix pgsql + Dovecot + dış gönderim yapılandırmasını doğrula ve onar."""
    from management.mail_stack_health import verify_mail_stack
    from management.outbound_autoconfig import ensure_outbound_delivery

    ensure_outbound_delivery(fix=True, full_heal=True)
    return verify_mail_stack(fix=True)
