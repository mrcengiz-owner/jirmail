"""Servis izleme için django-ninja router.

Endpoint'ler:
    GET    /api/monitoring/queue              postfix kuyruğu
    GET    /api/monitoring/queue/count        kuyruktaki mail sayısı
    DELETE /api/monitoring/queue/{queue_id}   kuyruktan sil
    POST   /api/monitoring/queue/flush        kuyruğu flush
    POST   /api/monitoring/queue/delete-all   kuyruktaki herşeyi sil
    GET    /api/monitoring/queue/{queue_id}/view   mesaj içeriği (postcat)
    POST   /api/monitoring/queue/{queue_id}/hold
    POST   /api/monitoring/queue/{queue_id}/release
    GET    /api/monitoring/dnsbl/{ip}         DNSBL kontrol
    GET    /api/monitoring/reputation         son N saat istatistik
    GET    /api/monitoring/logs/stream        SSE log streaming (Django path)
"""
from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from . import postfix_inspector
from .dnsbl_checker import check_ip
from .log_streamer import log_sse_response
from .reputation import compute_stats


router = Router()


@router.get('/queue', summary='Postfix mail queue')
def list_queue(request: HttpRequest):
    return {'success': True, 'entries': postfix_inspector.list_queue()}


@router.get('/queue/count', summary='Queue sayısı')
def queue_count(request: HttpRequest):
    return {'success': True, 'count': postfix_inspector.get_queue_count()}


@router.delete('/queue/{queue_id}', summary='Kuyruktan sil')
def delete_queue_entry(request: HttpRequest, queue_id: str):
    return postfix_inspector.delete_message(queue_id)


@router.post('/queue/flush', summary='Kuyruğu flush et')
def flush_queue(request: HttpRequest):
    return postfix_inspector.flush_queue()


@router.post('/queue/delete-all', summary='Tüm kuyruğu sil')
def delete_all_queue(request: HttpRequest):
    return postfix_inspector.delete_all()


@router.get('/queue/{queue_id}/view', summary='Mesaj içeriği')
def view_queue_entry(request: HttpRequest, queue_id: str):
    return postfix_inspector.view_message(queue_id)


@router.post('/queue/{queue_id}/hold', summary='Hold')
def hold_queue_entry(request: HttpRequest, queue_id: str):
    return postfix_inspector.hold_message(queue_id)


@router.post('/queue/{queue_id}/release', summary='Hold\'dan çıkar')
def release_queue_entry(request: HttpRequest, queue_id: str):
    return postfix_inspector.release_message(queue_id)


@router.get('/dnsbl/{ip}', summary='IP DNSBL kontrol')
def dnsbl_check(request: HttpRequest, ip: str):
    return check_ip(ip)


@router.get('/reputation', summary='Mail reputation istatistik')
def reputation(request: HttpRequest, window_hours: int = 24):
    return {'success': True, **compute_stats(window_hours=window_hours)}


def logs_stream(request: HttpRequest):
    """SSE — mail log canlı yayını."""
    container = request.GET.get('container', 'jir_postfix')
    try:
        lines = int(request.GET.get('lines', '100'))
    except ValueError:
        lines = 100
    return log_sse_response(container, lines=lines)
