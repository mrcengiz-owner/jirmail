FROM alpine:3.19

# Alpine 3.19: IMAP ana dovecot paketinde; postfix ayrı konteyner (jir_postfix)
RUN apk add --no-cache \
    dovecot \
    dovecot-pop3d \
    dovecot-lmtpd \
    dovecot-pgsql \
    ca-certificates \
    bash \
    gettext \
    openssl

RUN mkdir -p /etc/dovecot /var/mail/vhosts /usr/share/jir-mail/dovecot-templates && \
    chown -R root:mail /var/mail && \
    chmod 771 /var/mail

# Şablonlar volume dışında — jir_dovecot_data /etc/dovecot'u mount edince silinmesin diye
COPY dovecot.conf.tpl /usr/share/jir-mail/dovecot-templates/dovecot.conf.tpl
COPY dovecot-sql.conf.ext.tpl /usr/share/jir-mail/dovecot-templates/dovecot-sql.conf.ext.tpl
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Şablon + entrypoint ile üretilen config geçerli mi (manage_sieve vb. yakalanır)
RUN DB_HOST=127.0.0.1 DB_PORT=5432 DB_NAME=jir DB_USER=jir DB_PASS=jir MAIL_DOMAIN=mail.local \
    /entrypoint.sh doveconf -n >/dev/null

EXPOSE 993

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dovecot", "-F"]
