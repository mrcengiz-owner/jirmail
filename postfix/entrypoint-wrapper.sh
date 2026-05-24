#!/bin/sh
# boky/postfix: her konteyner start'ta Jîr-Mail init + doğrulama, sonra orijinal süreç
set -e

# boky/postfix: /docker-init.d/*.sh zaten startup sırasında çalışır — tekrar etme (çift reload).
# Özel init: docker-init.d/ içindeki script'ler.
if [ -x /scripts/run.sh ]; then
  exec /scripts/run.sh "$@"
fi
if [ -x /startup.sh ]; then
  exec /startup.sh "$@"
fi
if [ $# -gt 0 ]; then
  exec "$@"
fi
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf 2>/dev/null || exec postfix start-fg
