# Dovecot — Jîr-Mail (şablon). MAIL_DOMAIN entrypoint ile yazılır.
# Sertifika üretimde TLS ile değiştirin (Let's Encrypt vb.).

listen = *, ::
# Gönderim Postfix (587); Sieve için pigeonhole gerekir — Alpine imajında yok
protocols = imap pop3 lmtp

log_path = /var/log/dovecot.log
info_log_path = /var/log/dovecot-info.log

ssl = required
ssl_cert = </etc/dovecot/ssl/dovecot.crt
ssl_key = </etc/dovecot/ssl/dovecot.key

mail_location = maildir:/var/mail/vhosts/%d/%n

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
  quota_rule = *:storage=%{Userdb:quota_bytes}b
  quota_rule2 = *:messages=0
  quota_exceeded = 552 5.2.2 Mailbox full
}

auth_mechanisms = plain login cram-md5
first_valid_uid = 5000
last_valid_uid = 5000

auth_default_realm = $MAIL_DOMAIN
