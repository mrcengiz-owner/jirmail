#!/bin/sh
# Init zinciri bittikten sonra master sürecini doğrula (source edilen script exit hatalarına karşı).
. /docker-init.d/_jirmail-common.sh

if postfix status >/dev/null 2>&1; then
  echo "[jirmail-postfix] master zaten çalışıyor"
else
  echo "[jirmail-postfix] master başlatılıyor (98-ensure-master)…"
  postfix start 2>&1 || echo "[jirmail-postfix] UYARI: postfix start başarısız — boky startup devam edecek" >&2
fi
