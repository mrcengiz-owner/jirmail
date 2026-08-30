"""Dahili mail PKI zincir doğrulama testleri."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from installer.mail_pki import (
    MailPkiMaterial,
    ensure_mail_pki_files,
    generate_mail_pki,
    mail_pki_chain_ok,
)


class MailPkiChainTests(unittest.TestCase):
    def test_generated_pki_chain_ok(self):
        material = generate_mail_pki(
            common_name='mail.example.com',
            dns_names=['mail.example.com', 'postfix', 'localhost'],
        )
        self.assertTrue(mail_pki_chain_ok(material))
        self.assertIn(b'BEGIN CERTIFICATE', material.ca_cert_pem)
        self.assertIn(b'BEGIN RSA PRIVATE KEY', material.server_key_pem)
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID

        ca = x509.load_pem_x509_certificate(material.ca_cert_pem)
        ku = ca.extensions.get_extension_for_oid(ExtensionOID.KEY_USAGE).value
        self.assertTrue(ku.key_cert_sign)

    def test_mismatched_ca_fails(self):
        a = generate_mail_pki(common_name='mail.a.com', dns_names=['mail.a.com'])
        b = generate_mail_pki(common_name='mail.b.com', dns_names=['mail.b.com'])
        mixed = MailPkiMaterial(
            ca_cert_pem=a.ca_cert_pem,
            server_cert_pem=b.server_cert_pem,
            server_key_pem=b.server_key_pem,
        )
        self.assertFalse(mail_pki_chain_ok(mixed))

    def test_ensure_files_repairs_broken_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            tls_dir = Path(tmp)
            good = generate_mail_pki(common_name='mail.x.com', dns_names=['mail.x.com'])
            (tls_dir / 'ca.crt').write_bytes(good.ca_cert_pem)
            other = generate_mail_pki(common_name='mail.y.com', dns_names=['mail.y.com'])
            (tls_dir / 'server.crt').write_bytes(other.server_cert_pem)
            (tls_dir / 'server.key').write_bytes(other.server_key_pem)
            repaired = ensure_mail_pki_files(
                tls_dir,
                mail_hostname='mail.x.com',
                mail_domain='x.com',
            )
            self.assertTrue(mail_pki_chain_ok(repaired))
            self.assertTrue(mail_pki_chain_ok(
                MailPkiMaterial(
                    ca_cert_pem=(tls_dir / 'ca.crt').read_bytes(),
                    server_cert_pem=(tls_dir / 'server.crt').read_bytes(),
                    server_key_pem=(tls_dir / 'server.key').read_bytes(),
                )
            ))
