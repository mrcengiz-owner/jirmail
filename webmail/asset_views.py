"""Webmail statik dosyaları — Traefik yalnızca /webmail/ yönlendirdiğinde CSS/JS garantisi."""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponseNotModified
from django.views.decorators.http import require_GET

# Kesin izin listesi + webmail css/js önekleri
ALLOWED_EXACT = frozenset({
    'brand/logo-icon.svg',
    'brand/favicon.svg',
})

CONTENT_TYPES = {
    '.css': 'text/css; charset=utf-8',
    '.js': 'application/javascript; charset=utf-8',
    '.svg': 'image/svg+xml',
}


def _is_allowed(relative_path: str) -> bool:
    if relative_path in ALLOWED_EXACT:
        return True
    if relative_path.startswith('css/webmail') and relative_path.endswith('.css'):
        return True
    if relative_path.startswith('js/webmail/') and relative_path.endswith('.js'):
        return True
    return False


def _resolve_asset(relative_path: str) -> Path | None:
    relative_path = relative_path.lstrip('/').replace('\\', '/')
    if not _is_allowed(relative_path):
        return None
    static_root = Path(settings.STATIC_ROOT)
    static_src = Path(settings.BASE_DIR) / 'static'
    for path in (static_root / relative_path, static_src / relative_path):
        if path.is_file():
            return path
    return None


@require_GET
def serve_asset(request, asset_path: str):
    path = _resolve_asset(asset_path)
    if not path:
        raise Http404('Asset not found')

    stat = path.stat()
    mtime = stat.st_mtime
    etag = f'"{int(mtime)}-{stat.st_size}"'
    if request.META.get('HTTP_IF_NONE_MATCH') == etag:
        return HttpResponseNotModified()

    suffix = path.suffix.lower()
    content_type = CONTENT_TYPES.get(suffix, 'application/octet-stream')
    response = FileResponse(path.open('rb'), content_type=content_type)
    response['Cache-Control'] = 'public, max-age=3600'
    response['ETag'] = etag
    return response
