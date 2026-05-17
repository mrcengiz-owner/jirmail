#!/bin/sh
# boky ana betiği sonrası: gönderen kısıtını tekrar kaldır (deploy sonrası güvence)
set -e
postconf -e 'smtpd_sender_restrictions=permit'
postconf -e 'smtpd_client_restrictions=permit'
echo "[jirmail-postfix] smtpd_sender_restrictions=permit (99 override)"
