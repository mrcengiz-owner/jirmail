#!/bin/sh
# boky/postfix: her konteyner start'ta Jîr-Mail init + doğrulama, sonra orijinal süreç
set -e

echo "[jirmail-postfix] entrypoint: init scripts"
for s in /docker-init.d/*.sh; do
  [ -f "$s" ] || continue
  echo "[jirmail-postfix] running $(basename "$s")"
  sh "$s"
done

# boky varsayılan: tini altında supervisord veya startup script
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
