"""Jîr-Mail iç ağ PKI — panel ↔ Postfix ↔ Dovecot uçtan uca TLS."""
from __future__ import annotations

import io
import logging
import tarfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger(__name__)

JIR_MAIL_TLS_VOLUME = 'jir_mail_tls'
MAIL_TLS_MOUNT = '/etc/jir-mail/tls'
CA_FILENAME = 'ca.crt'
SERVER_CERT_FILENAME = 'server.crt'
SERVER_KEY_FILENAME = 'server.key'
_TLS_FILENAMES = (CA_FILENAME, SERVER_CERT_FILENAME, SERVER_KEY_FILENAME)


@dataclass(frozen=True)
class MailPkiMaterial:
    ca_cert_pem: bytes
    server_cert_pem: bytes
    server_key_pem: bytes

    def as_volume_files(self) -> dict[str, bytes]:
        return {
            CA_FILENAME: self.ca_cert_pem,
            SERVER_CERT_FILENAME: self.server_cert_pem,
            SERVER_KEY_FILENAME: self.server_key_pem,
        }


def _tar_archive(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mode = 0o644 if name.endswith('.crt') else 0o600
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def generate_mail_pki(
    *,
    common_name: str,
    dns_names: list[str],
    valid_days: int = 825,
) -> MailPkiMaterial:
    """Dahili CA + sunucu sertifikası (panel, Postfix, Dovecot SAN)."""
    names = sorted({n.strip() for n in dns_names if n and n.strip()})
    if not names:
        names = [common_name]

    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Jir-Mail Internal CA')])
    now = datetime.now(timezone.utc)
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(ca_key, hashes.SHA256())
    )

    server_key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    server_subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    san = x509.SubjectAlternativeName([x509.DNSName(n) for n in names])
    server_cert = (
        x509.CertificateBuilder()
        .subject_name(server_subject)
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=True,
                content_commitment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(ca_key, hashes.SHA256())
    )

    def _pem_cert(cert: x509.Certificate) -> bytes:
        return cert.public_bytes(serialization.Encoding.PEM)

    def _pem_key(key: rsa.RSAPrivateKey) -> bytes:
        return key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )

    return MailPkiMaterial(
        ca_cert_pem=_pem_cert(ca_cert),
        server_cert_pem=_pem_cert(server_cert),
        server_key_pem=_pem_key(server_key),
    )


def _ensure_volume(client, name: str) -> None:
    try:
        client.volumes.get(name)
    except Exception:
        client.volumes.create(name=name)


def _dispose_container(container) -> None:
    """stop() Gunicorn zaman aşımına yol açabiliyor; doğrudan force remove."""
    if not container:
        return
    try:
        container.remove(force=True)
    except Exception as exc:
        logger.debug('PKI yardımcı konteyner kaldırılamadı: %s', exc)


def _with_tls_volume_container(client, volume_name: str, *, read_only: bool = True):
    """Volume mount edilmiş kısa ömürlü alpine konteyner."""
    container = client.containers.create(
        'alpine:3.19',
        ['sleep', '300'],
        volumes={volume_name: {'bind': MAIL_TLS_MOUNT, 'mode': 'ro' if read_only else 'rw'}},
    )
    container.start()
    return container


def _exec_cat(container, filename: str) -> bytes:
    """Docker get_archive tek dosyada 404 verebilir; cat güvenilir."""
    path = f'{MAIL_TLS_MOUNT}/{filename}'
    exit_code, output = container.exec_run(['cat', path])
    if exit_code != 0:
        raise FileNotFoundError(f'{path} okunamadı (exit {exit_code})')
    if not output:
        raise FileNotFoundError(f'{path} boş')
    return output


def _volume_has_complete_pki(client, volume_name: str) -> bool:
    container = None
    try:
        container = _with_tls_volume_container(client, volume_name, read_only=True)
        for name in _TLS_FILENAMES:
            exit_code, _ = container.exec_run(['test', '-s', f'{MAIL_TLS_MOUNT}/{name}'])
            if exit_code != 0:
                return False
        return True
    except Exception:
        return False
    finally:
        _dispose_container(container)


def _write_volume_files(client, volume_name: str, files: dict[str, bytes]) -> None:
    container = None
    try:
        container = _with_tls_volume_container(client, volume_name, read_only=False)
        container.exec_run(['mkdir', '-p', MAIL_TLS_MOUNT])
        container.put_archive(MAIL_TLS_MOUNT, _tar_archive(files))
        for name in files:
            exit_code, _ = container.exec_run(['test', '-s', f'{MAIL_TLS_MOUNT}/{name}'])
            if exit_code != 0:
                raise RuntimeError(f'PKI dosyası yazılamadı: {MAIL_TLS_MOUNT}/{name}')
    finally:
        _dispose_container(container)


def volume_has_mail_pki(client: Any, volume_name: str = JIR_MAIL_TLS_VOLUME) -> bool:
    return _volume_has_complete_pki(client, volume_name)


def ensure_mail_pki_volume(
    client: Any,
    *,
    mail_hostname: str,
    mail_domain: str,
    postfix_container: str,
    dovecot_container: str,
    force: bool = False,
    load_if_exists: bool = True,
) -> MailPkiMaterial:
    """Docker volume jir_mail_tls içinde CA + sunucu sertifikası."""
    _ensure_volume(client, JIR_MAIL_TLS_VOLUME)
    if not force and _volume_has_complete_pki(client, JIR_MAIL_TLS_VOLUME):
        if not load_if_exists:
            logger.info('PKI volume mevcut; PEM okuma atlandı (mount üzerinden kullanılır).')
            return MailPkiMaterial(ca_cert_pem=b'', server_cert_pem=b'', server_key_pem=b'')
        try:
            return load_mail_pki_from_volume(client)
        except Exception as exc:
            logger.warning('PKI volume okunamadı, yeniden oluşturuluyor: %s', exc)

    dns_names = [
        mail_hostname,
        mail_domain,
        f'mail.{mail_domain}',
        postfix_container,
        dovecot_container,
        'localhost',
    ]
    material = generate_mail_pki(common_name=mail_hostname, dns_names=dns_names)
    _write_volume_files(client, JIR_MAIL_TLS_VOLUME, material.as_volume_files())
    logger.info('Mail PKI oluşturuldu (volume=%s)', JIR_MAIL_TLS_VOLUME)
    return material


def load_mail_pki_from_volume(client: Any) -> MailPkiMaterial:
    """Mevcut volume'dan PEM oku (exec cat)."""
    container = None
    try:
        container = _with_tls_volume_container(client, JIR_MAIL_TLS_VOLUME, read_only=True)
        return MailPkiMaterial(
            ca_cert_pem=_exec_cat(container, CA_FILENAME),
            server_cert_pem=_exec_cat(container, SERVER_CERT_FILENAME),
            server_key_pem=_exec_cat(container, SERVER_KEY_FILENAME),
        )
    finally:
        _dispose_container(container)


def mail_tls_volume_mount(*, read_only: bool = True) -> dict[str, dict[str, str]]:
    return {
        JIR_MAIL_TLS_VOLUME: {
            'bind': MAIL_TLS_MOUNT,
            'mode': 'ro' if read_only else 'rw',
        },
    }


def postfix_tls_environment() -> dict[str, str]:
    """boky/postfix: submission üzerinde zorunlu TLS."""
    cert = f'{MAIL_TLS_MOUNT}/{SERVER_CERT_FILENAME}'
    key = f'{MAIL_TLS_MOUNT}/{SERVER_KEY_FILENAME}'
    ca = f'{MAIL_TLS_MOUNT}/{CA_FILENAME}'
    return {
        'POSTFIX_smtpd_tls_security_level': 'encrypt',
        'POSTFIX_smtpd_tls_cert_file': cert,
        'POSTFIX_smtpd_tls_key_file': key,
        'POSTFIX_smtpd_tls_CAfile': ca,
        'POSTFIX_smtpd_tls_auth_only': 'yes',
        'POSTFIX_smtpd_tls_mandatory_protocols': '!SSLv2, !SSLv3, !TLSv1, !TLSv1.1',
        'POSTFIX_smtpd_tls_mandatory_ciphers': 'high',
    }


def write_ca_to_path(ca_pem: bytes, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ca_pem)
    path.chmod(0o644)
    return path


def _tls_dir_complete(tls_dir: Path) -> bool:
    return all((tls_dir / name).is_file() and (tls_dir / name).stat().st_size > 0 for name in _TLS_FILENAMES)


def ensure_mail_pki_files(
    tls_dir: Path,
    *,
    mail_hostname: str,
    mail_domain: str,
    postfix_host: str = 'postfix',
    dovecot_host: str = 'dovecot',
    force: bool = False,
) -> MailPkiMaterial:
    """Compose: paylaşılan volume dizinine PKI yaz (Docker API yok)."""
    tls_dir = Path(tls_dir)
    tls_dir.mkdir(parents=True, exist_ok=True)
    if not force and _tls_dir_complete(tls_dir):
        return load_mail_pki_from_directory(tls_dir)

    dns_names = [
        mail_hostname,
        mail_domain,
        f'mail.{mail_domain}',
        postfix_host,
        dovecot_host,
        'jir_postfix',
        'jir_dovecot',
        'localhost',
    ]
    material = generate_mail_pki(common_name=mail_hostname, dns_names=dns_names)
    for name, data in material.as_volume_files().items():
        dest = tls_dir / name
        dest.write_bytes(data)
        dest.chmod(0o644 if name.endswith('.crt') else 0o600)
    logger.info('Mail PKI yazıldı: %s', tls_dir)
    return material


def load_mail_pki_from_directory(tls_dir: Path) -> MailPkiMaterial:
    tls_dir = Path(tls_dir)
    return MailPkiMaterial(
        ca_cert_pem=(tls_dir / CA_FILENAME).read_bytes(),
        server_cert_pem=(tls_dir / SERVER_CERT_FILENAME).read_bytes(),
        server_key_pem=(tls_dir / SERVER_KEY_FILENAME).read_bytes(),
    )
