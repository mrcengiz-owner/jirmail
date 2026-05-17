# Dovecot — Jîr-Mail (şablon). MAIL_DOMAIN entrypoint ile yazılır.

listen = *, ::
# Gönderim Postfix (587); Sieve için pigeonhole gerekir — Alpine imajında yok
protocols = imap pop3 lmtp

# docker logs için (varsayılan dosya logları stdout'a düşmez)
log_path = /dev/stderr
info_log_path = /dev/stderr

# IMAPS 993 zaten ssl=yes; global required düz 143 ile çakışabiliyor
ssl = yes
ssl_cert = </etc/dovecot/ssl/dovecot.crt
ssl_key = </etc/dovecot/ssl/dovecot.key

mail_location = maildir:/var/mail/vhosts/%d/%n

# Minimal conf.d include yok — IMAPS 993 açıkça tanımlanmalı
service imap-login {
  inet_listener imap {
    port = 0
  }
  inet_listener imaps {
    port = 993
    ssl = yes
  }
}

service pop3-login {
  inet_listener pop3 {
    port = 0
  }
  inet_listener pop3s {
    port = 995
    ssl = yes
  }
}

# Postfix → Dovecot teslimatı (gelen posta)
service lmtp {
  inet_listener lmtp {
    port = 24
  }
}

passdb {
  driver = sql
  args = /etc/dovecot/dovecot-sql.conf.ext
}

userdb {
  driver = sql
  args = /etc/dovecot/dovecot-sql.conf.ext
}

plugin {
  quota = maildir:User quota
  # Sabit kota — %{userdb:...} Alpine Dovecot 2.3'te plugin aşamasında genişlemiyor
  quota_rule = *:storage=2G
  quota_rule2 = *:messages=0
  quota_exceeded = 552 5.2.2 Mailbox full
}

protocol imap {
  mail_plugins = $mail_plugins quota
}

protocol pop3 {
  mail_plugins = $mail_plugins quota
}

auth_mechanisms = plain login
# Tam e-posta ile giriş (user@domain); realm ayrıştırmasını bozmasın
auth_username_format = %Lu
first_valid_uid = 5000
last_valid_uid = 5000
