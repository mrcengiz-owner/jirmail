# boky/postfix + gelen posta (MX) yapılandırması
FROM boky/postfix:latest

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        postgresql-client gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY docker-init.d/ /docker-init.d/
COPY pgsql-virtual-mailboxes.cf.tpl pgsql-virtual-domains.cf.tpl /usr/share/jir-mail/postfix-templates/
RUN chmod +x /docker-init.d/*.sh
ENV JIR_POSTFIX_TEMPLATES=/usr/share/jir-mail/postfix-templates
