"""Postfix virtual_mailbox_maps yenileme (hesap ekleme/silme sonrası)."""
from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)


def reload_virtual_mailboxes() -> bool:
    """jir_postfix içinde inbound init script mantığını tekrar çalıştır."""
    container = os.getenv('JIR_CONTAINER_POSTFIX', 'jir_postfix')
    script = '/docker-init.d/10-jirmail-inbound.sh'
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
        return True
    except FileNotFoundError:
        logger.debug('docker CLI yok — postfix map yenileme atlandı')
        return False
    except Exception as exc:
        logger.warning('Postfix virtual_mailbox yenileme: %s', exc)
        return False
