"""Programatik Docker servis tanımları.

docker-compose.yml'in yerini alır: Django runtime'da bu tanımları okuyup
Docker SDK üzerinden container'ları yaratır. Her servis için image, env,
volume, port, network ve healthcheck bilgileri bu modülde tutulur.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


from installer.mail_pki import JIR_MAIL_TLS_VOLUME, MAIL_TLS_MOUNT, postfix_tls_environment

JIR_NETWORK = 'jir_network'
JIR_DOVECOT_IMAGE = 'jir-mail-dovecot:latest'


@dataclass
class ServiceSpec:
    """Tek bir Docker servisinin spesifikasyonu."""
    key: str
    name: str
    image: str
    environment: dict = field(default_factory=dict)
    ports: dict = field(default_factory=dict)
    volumes: dict = field(default_factory=dict)
    command: list | None = None
    restart_policy: str = 'unless-stopped'
    healthcheck: dict | None = None
    hostname: str | None = None
    network: str = JIR_NETWORK
    depends_on: list = field(default_factory=list)


def build_specs(config: dict) -> list[ServiceSpec]:
    """Kurulum konfigürasyonundan tüm servis spec'lerini üretir.

    config örneği:
        {
            'domain': 'jircode.com',
            'mail_hostname': 'mail.jircode.com',
            'postgres_password': '...',
            'postgres_db': 'jir_mail_prod',
            'postgres_user': 'postgres',
            'jir_local_key': '...',
        }
    """
    domain = config['domain']
    mail_hostname = config.get('mail_hostname', f'mail.{domain}')
    pg_password = config['postgres_password']
    pg_db = config.get('postgres_db', 'jir_mail_prod')
    pg_user = config.get('postgres_user', 'postgres')

    specs: list[ServiceSpec] = []

    specs.append(ServiceSpec(
        key='postgres',
        name='jir_postgres',
        image='postgres:17-alpine',
        environment={
            'POSTGRES_DB': pg_db,
            'POSTGRES_USER': pg_user,
            'POSTGRES_PASSWORD': pg_password,
        },
        volumes={
            'jir_postgres_data': {'bind': '/var/lib/postgresql/data', 'mode': 'rw'},
        },
        healthcheck={
            'test': ['CMD-SHELL', f'pg_isready -U {pg_user}'],
            'interval': 10 * 1_000_000_000,
            'timeout': 5 * 1_000_000_000,
            'retries': 5,
        },
    ))

    specs.append(ServiceSpec(
        key='redis',
        name='jir_redis',
        image='redis:7-alpine',
        volumes={
            'jir_redis_data': {'bind': '/data', 'mode': 'rw'},
        },
        healthcheck={
            'test': ['CMD', 'redis-cli', 'ping'],
            'interval': 10 * 1_000_000_000,
            'timeout': 5 * 1_000_000_000,
            'retries': 5,
        },
    ))

    pf_env = {
        'ALLOWED_SENDER_DOMAINS': domain,
        'HOSTNAME': mail_hostname,
        'POSTFIX_mynetworks': '127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16',
    }
    pf_env.update(postfix_tls_environment())

    specs.append(ServiceSpec(
        key='postfix',
        name='jir_postfix',
        image='boky/postfix:latest',
        hostname=mail_hostname,
        environment=pf_env,
        ports={
            '25/tcp': 25,
            '587/tcp': 587,
        },
        volumes={
            'jir_postfix_data': {'bind': '/etc/postfix', 'mode': 'rw'},
            'jir_mail_data': {'bind': '/var/mail', 'mode': 'rw'},
            JIR_MAIL_TLS_VOLUME: {'bind': MAIL_TLS_MOUNT, 'mode': 'ro'},
        },
        depends_on=['postgres'],
    ))

    specs.append(ServiceSpec(
        key='dovecot',
        name='jir_dovecot',
        image=JIR_DOVECOT_IMAGE,
        environment={
            'DB_HOST': 'jir_postgres',
            'DB_PORT': '5432',
            'DB_NAME': pg_db,
            'DB_USER': pg_user,
            'DB_PASS': pg_password,
            'MAIL_DOMAIN': domain,
        },
        ports={
            '993/tcp': 993,
        },
        volumes={
            'jir_mail_data': {'bind': '/var/mail', 'mode': 'rw'},
            JIR_MAIL_TLS_VOLUME: {'bind': MAIL_TLS_MOUNT, 'mode': 'ro'},
        },
        depends_on=['postgres'],
    ))

    return specs


def order_specs(specs: list[ServiceSpec]) -> list[ServiceSpec]:
    """depends_on'a göre topological sırala."""
    by_key = {s.key: s for s in specs}
    ordered: list[ServiceSpec] = []
    seen: set[str] = set()

    def visit(key: str):
        if key in seen or key not in by_key:
            return
        seen.add(key)
        for dep in by_key[key].depends_on:
            visit(dep)
        ordered.append(by_key[key])

    for s in specs:
        visit(s.key)

    return ordered
