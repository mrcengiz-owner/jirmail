# boky/postfix + gelen posta (MX) yapılandırması
FROM boky/postfix:latest

USER root
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY docker-init.d/ /docker-init.d/
RUN chmod +x /docker-init.d/*.sh
