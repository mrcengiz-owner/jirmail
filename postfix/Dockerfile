# boky/postfix + gelen posta (MX) yapılandırması
FROM boky/postfix:latest

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postgresql-client gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY docker-init.d/ /docker-init.d/
COPY pgsql-virtual-mailboxes.cf.tpl pgsql-virtual-domains.cf.tpl /usr/share/jir-mail/postfix-templates/
COPY entrypoint-wrapper.sh /usr/local/bin/jir-postfix-entrypoint.sh
RUN chmod +x /docker-init.d/*.sh /usr/local/bin/jir-postfix-entrypoint.sh
ENV JIR_POSTFIX_TEMPLATES=/usr/share/jir-mail/postfix-templates
ENTRYPOINT ["/tini", "--", "/usr/local/bin/jir-postfix-entrypoint.sh"]
