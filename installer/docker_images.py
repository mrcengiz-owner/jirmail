"""Jîr-Mail özel Docker imajları (Dovecot passdb)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from django.conf import settings

logger = logging.getLogger(__name__)

JIR_DOVECOT_IMAGE = 'jir-mail-dovecot:latest'


def dovecot_build_context() -> Path:
    return Path(settings.BASE_DIR) / 'dovecot'


def ensure_jir_dovecot_image(
    client,
    *,
    force_rebuild: bool = False,
    log: Callable[[str], None] | None = None,
) -> str:
    """Repo içindeki dovecot/Dockerfile ile imaj oluştur veya yeniden kullan."""
    ctx = dovecot_build_context()
    dockerfile = ctx / 'Dockerfile'
    if not dockerfile.is_file():
        raise FileNotFoundError(f'Dovecot Dockerfile bulunamadı: {dockerfile}')

    def _say(msg: str) -> None:
        if log:
            log(msg)
        else:
            logger.info(msg)

    if not force_rebuild:
        try:
            client.images.get(JIR_DOVECOT_IMAGE)
            _say(f'Dovecot imajı mevcut: {JIR_DOVECOT_IMAGE}')
            return JIR_DOVECOT_IMAGE
        except Exception:
            pass

    _say(f'Dovecot imajı derleniyor: {JIR_DOVECOT_IMAGE} …')
    image, build_logs = client.images.build(
        path=str(ctx),
        tag=JIR_DOVECOT_IMAGE,
        rm=True,
        pull=False,
    )
    for chunk in build_logs or []:
        if isinstance(chunk, dict) and 'stream' in chunk:
            line = (chunk.get('stream') or '').strip()
            if line:
                _say(line[:300])
    tags = getattr(image, 'tags', None) or []
    _say(f'Dovecot imajı hazır: {", ".join(tags) or JIR_DOVECOT_IMAGE}')
    return JIR_DOVECOT_IMAGE


def _container_image_ref(container) -> str:
    try:
        container.reload()
    except Exception:
        pass
    tags = []
    try:
        img = container.image
        tags = list(getattr(img, 'tags', None) or [])
    except Exception:
        pass
    if tags:
        return ' '.join(tags).lower()
    try:
        return str(
            ((container.attrs or {}).get('Config') or {}).get('Image') or ''
        ).lower()
    except Exception:
        return ''


def dovecot_container_needs_rebuild(client, container_name: str) -> bool:
    """Stok dovecot/dovecot imajı veya eksik özel imaj → yeniden oluştur."""
    import docker

    try:
        c = client.containers.get(container_name)
    except docker.errors.NotFound:
        return True
    ref = _container_image_ref(c)
    if 'jir-mail-dovecot' in ref:
        return False
    if 'dovecot/dovecot' in ref or ref == 'dovecot' or ref.endswith(':latest') and 'dovecot' in ref:
        return True
    # Bilinmeyen imaj — güvenli tarafta yeniden kur
    return 'dovecot' in ref and 'jir-mail' not in ref
