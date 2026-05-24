"""Postfix virtual_mailbox_maps yenileme (hesap ekleme/silme sonrası)."""
from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def reload_virtual_mailboxes() -> bool:
    """Postfix yenile (pgsql harita anlık; docker yoksa no-op)."""
    try:
        from core.mail_provision import reload_postfix

        reload_postfix()
        return True
    except Exception as exc:
        logger.debug('postfix reload: %s', exc)

    container = os.getenv('JIR_CONTAINER_POSTFIX', 'jir_postfix')
    script = '/docker-init.d/10-jirmail-inbound.sh'
    transport_script = '/docker-init.d/31-jirmail-transport-maps.sh'
    try:
        result = subprocess.run(
            ['docker', 'exec', container, 'sh', script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.warning(
                'Postfix virtual_mailbox yenileme: %s',
                (result.stderr or result.stdout or '')[:500],
            )
            return False
        subprocess.run(
            ['docker', 'exec', container, 'sh', transport_script],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return True
    except FileNotFoundError:
        logger.debug('docker CLI yok — postfix map yenileme atlandı (pgsql canlı)')
        return True
    except Exception as exc:
        logger.warning('Postfix virtual_mailbox yenileme: %s', exc)
        return False
