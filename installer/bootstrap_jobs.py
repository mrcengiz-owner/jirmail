"""Uzun süren bootstrap — Gunicorn worker zaman aşımını önlemek için arka plan."""
from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_state: dict[str, Any] = {
    'status': 'idle',
    'result': None,
    'error': None,
}


def bootstrap_state_snapshot() -> dict[str, Any]:
    with _lock:
        out = {
            'status': _state.get('status', 'idle'),
            'error': _state.get('error'),
        }
        if _state.get('status') == 'done' and _state.get('result'):
            out['result'] = _state['result']
        return out


def start_bootstrap_async(cfg: dict[str, Any]) -> dict[str, Any]:
    """Bootstrap'ı arka planda başlat; hemen yanıt dön."""
    with _lock:
        if _state.get('status') == 'running':
            return {
                'status': 'running',
                'message': 'Bootstrap zaten çalışıyor.',
            }
        _state['status'] = 'running'
        _state['result'] = None
        _state['error'] = None

    def _worker() -> None:
        global _state
        try:
            from installer.single_server import bootstrap_single_server

            result = bootstrap_single_server(cfg)
            with _lock:
                _state = {
                    'status': 'done',
                    'result': result,
                    'error': None if result.get('success') else result.get('error'),
                }
        except Exception as exc:
            logger.exception('bootstrap worker')
            with _lock:
                _state = {
                    'status': 'error',
                    'result': None,
                    'error': str(exc),
                }

    threading.Thread(target=_worker, daemon=True, name='jir-bootstrap').start()
    return {
        'status': 'running',
        'message': 'Bootstrap arka planda başlatıldı. Durum için GET /api/installer/bootstrap-stack/status',
    }
