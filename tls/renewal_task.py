"""Celery task — TLS sertifika yenileme."""
from __future__ import annotations

import logging

from celery import shared_task

from .certbot_manager import renew_all


logger = logging.getLogger(__name__)


@shared_task(name='tls.renew_certificates')
def renew_certificates_task():
    """Haftalık olarak çalışır (Celery Beat ile)."""
    try:
        result = renew_all()
        logger.info('Certbot renew sonucu: %s', result)
        return result
    except Exception as exc:
        logger.exception('Certbot renew başarısız: %s', exc)
        return {'success': False, 'message': str(exc)}
