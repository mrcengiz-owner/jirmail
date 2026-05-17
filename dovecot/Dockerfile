FROM alpine:3.19

# Alpine 3.19: dovecot-imapd yok — IMAP ana dovecot paketinde; postfix ayrı konteyner (jir_postfix)
RUN apk add --no-cache \
    dovecot \
    dovecot-pop3d \
    dovecot-lmtpd \
    dovecot-pgsql \
    ca-certificates \
    bash \
    gettext \
    openssl

RUN mkdir -p /etc/dovecot /var/mail/vhosts && \
    chown -R root:mail /var/mail && \
    chmod 771 /var/mail

COPY dovecot.conf.tpl /etc/dovecot/dovecot.conf.tpl
COPY dovecot-sql.conf.ext.tpl /etc/dovecot/dovecot-sql.conf.ext.tpl
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 993

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dovecot", "-F"]
