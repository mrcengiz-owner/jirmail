"""Let's Encrypt sertifika yönetimi.

Docker container içinde `certbot/certbot` image'ı ile HTTP-01 challenge
yöntemini çalıştırır. Sertifikalar `jir_letsencrypt` volume'una yazılır;
Postfix ve Dovecot bu volume'u read-only mount eder.

Production'da port 80'ün dışarıya açık olması gerekir (HTTP-01 challenge
için Let's Encrypt sunucularının domain'e ulaşması lazım).
"""
from __future__ import annotations

import logging
import shlex
from typing import Iterable

from django.conf import settings


logger = logging.getLogger(__name__)


CERTBOT_IMAGE = 'certbot/certbot:latest'
LETSENCRYPT_VOLUME = 'jir_letsencrypt'
WEBROOT_VOLUME = 'jir_certbot_webroot'


def _get_docker_client():
    import docker
    docker_host = getattr(settings, 'DOCKER_HOST', None) or 'unix://var/run/docker.sock'
    return docker.DockerClient(base_url=docker_host, timeout=120)


class CertbotManager:
    """Certbot komutlarını Docker üzerinden çalıştıran sınıf."""

    def __init__(self, email: str, staging: bool = False):
        self.email = email
        self.staging = staging

    def _run(self, cmd: list[str]) -> tuple[int, str]:
        client = _get_docker_client()
        try:
            client.images.get(CERTBOT_IMAGE)
        except Exception:
            client.images.pull(CERTBOT_IMAGE)

        for vol in (LETSENCRYPT_VOLUME, WEBROOT_VOLUME):
            try:
                client.volumes.get(vol)
            except Exception:
                client.volumes.create(vol)

        volumes = {
            LETSENCRYPT_VOLUME: {'bind': '/etc/letsencrypt', 'mode': 'rw'},
            WEBROOT_VOLUME: {'bind': '/var/www/certbot', 'mode': 'rw'},
        }

        try:
            container = client.containers.run(
                CERTBOT_IMAGE,
                command=cmd,
                volumes=volumes,
                ports={'80/tcp': 80},
                remove=True,
                detach=False,
                stdout=True,
                stderr=True,
            )
            output = container.decode('utf-8') if isinstance(container, bytes) else str(container)
            return 0, output
        except Exception as exc:
            return 1, str(exc)
        finally:
            try:
                client.close()
            except Exception:
                pass

    def request(self, domains: Iterable[str]) -> dict:
        """Verilen domain(ler) için yeni sertifika al."""
        domain_list = list(domains)
        if not domain_list:
            return {'success': False, 'message': 'En az bir domain gerekli'}

        cmd = ['certonly', '--standalone', '--non-interactive', '--agree-tos',
               '-m', self.email]
        if self.staging:
            cmd.append('--staging')
        for d in domain_list:
            cmd.extend(['-d', d])

        logger.info('Certbot request: %s', ' '.join(shlex.quote(c) for c in cmd))
        code, output = self._run(cmd)
        success = code == 0 and 'Successfully received certificate' in output
        return {
            'success': success or code == 0,
            'output': output[:5000],
            'exit_code': code,
        }

    def renew(self) -> dict:
        """Yenilemeye uygun tüm sertifikaları yenile."""
        cmd = ['renew', '--non-interactive', '--quiet']
        code, output = self._run(cmd)
        return {'success': code == 0, 'output': output[:5000], 'exit_code': code}


def request_certificate(domain: str, email: str, *, mail_subdomain: str = 'mail', staging: bool = False) -> dict:
    """Hem ana domain hem de mail.<domain> için sertifika al."""
    manager = CertbotManager(email=email, staging=staging)
    domains = [f'{mail_subdomain}.{domain}']
    return manager.request(domains)


def renew_all(email: str = '') -> dict:
    """Tüm sertifikaları yenile (Celery Beat haftalık çalıştırır)."""
    manager = CertbotManager(email=email or 'admin@localhost')
    return manager.renew()
