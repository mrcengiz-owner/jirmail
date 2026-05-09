FROM alpine:3.19

RUN apk add --no-cache dovecot dovecot-pop3d dovecot-imapd dovecot-lmtpd \
    dovecot-pgsql postfix ca-certificates bash openrc

# Dovecot config from env
RUN mkdir -p /etc/dovecot

# Copy templates
COPY dovecot.conf /etc/dovecot/dovecot.conf
COPY dovecot-sql.conf.ext /etc/dovecot/dovecot-sql.conf.ext.tpl

# Create entrypoint to render env vars
COPY <<EOF /entrypoint.sh
#!/bin/bash
sed "s/\${DB_HOST}/$DB_HOST/g;s/\${DB_PORT}/$DB_PORT/g;s/\${DB_NAME}/$DB_NAME/g;s/\${DB_USER}/$DB_USER/g;s/\${DB_PASS}/$DB_PASS/g" /etc/dovecot/dovecot-sql.conf.ext.tpl > /etc/dovecot/dovecot-sql.conf.ext
exec "$@"
EOF

RUN chmod +x /entrypoint.sh

# Create vmail directory
RUN mkdir -p /var/mail/vhosts && \
    chown -R root:mail /var/mail && \
    chmod 771 /var/mail

EXPOSE 993 143 587 465

ENTRYPOINT ["/entrypoint.sh"]
CMD ["dovecot", "-F"]