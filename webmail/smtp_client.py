"""SMTP submission istemcisi.

Kullanıcı kendi mail hesabıyla SMTP submission portu (587, STARTTLS) üzerinden
Postfix'e bağlanır. SASL auth ile mail gönderir.
"""
from __future__ import annotations

import logging
import socket
import smtplib
import ssl

logger = logging.getLogger(__name__)
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from django.conf import settings

from management.mail_service_endpoint import resolve_mail_endpoint
from management.mail_tls import smtp_starttls_required, smtp_tls_context


def _smtp_auth_supported(smtp: smtplib.SMTP) -> bool:
    try:
        return bool(smtp.has_extn('auth'))
    except Exception:
        return False


def _smtp_submit(
    smtp: smtplib.SMTP,
    *,
    account,
    password: str,
    msg: EmailMessage,
    recipients: list[str],
) -> None:
    """587 submission: zorunlu STARTTLS (e2e); AUTH yalnızca sunucu destekliyorsa."""
    smtp.ehlo()
    if smtp_starttls_required():
        if not smtp.has_extn('starttls'):
            raise smtplib.SMTPNotSupportedError('SMTP STARTTLS zorunlu ancak sunucu desteklemiyor.')
        smtp.starttls(context=smtp_tls_context())
        smtp.ehlo()
    elif smtp.has_extn('starttls'):
        smtp.starttls(context=smtp_tls_context())
        smtp.ehlo()
    if _smtp_auth_supported(smtp):
        if not password:
            raise ValueError('SMTP sunucusu kimlik doğrulama istiyor ancak parola verilmedi.')
        smtp.login(account.email, password)
    smtp.send_message(msg, from_addr=account.email, to_addrs=recipients)


def _message_id_domain(account) -> str:
    """Message-ID domain — domain FK yoksa e-postadan türet."""
    try:
        domain = getattr(account, 'domain', None)
        if domain is not None and getattr(domain, 'name', None):
            return domain.name
    except Exception:
        pass
    email = getattr(account, 'email', '') or ''
    if '@' in email:
        return email.split('@', 1)[1]
    return 'localhost'


def send_mail(account, password: str, *, to: list[str] | str, subject: str, body_text: str,
              body_html: str = '', cc: list[str] | None = None, bcc: list[str] | None = None,
              attachments: list[dict] | None = None) -> dict:
    """Postfix submission portu (587) üzerinden mail gönderir.

    attachments: [{'filename': 'a.pdf', 'mime_type': 'application/pdf', 'content': bytes}]
    """
    try:
        host, port = resolve_mail_endpoint(
            'postfix',
            int(getattr(settings, 'SMTP_PORT', 587)),
            auth_submission=True,
        )

        msg = EmailMessage()
        local_part = account.email.split('@')[0] if '@' in account.email else account.email
        msg['From'] = formataddr((local_part, account.email))
        msg['To'] = ', '.join(to) if isinstance(to, list) else to
        if cc:
            msg['Cc'] = ', '.join(cc)
        msg['Subject'] = subject or ''
        msg['Message-ID'] = make_msgid(domain=_message_id_domain(account))

        msg.set_content(body_text or '')
        if body_html:
            msg.add_alternative(body_html, subtype='html')

        for att in (attachments or []):
            content = att.get('content', b'')
            maintype, _, subtype = (att.get('mime_type') or 'application/octet-stream').partition('/')
            msg.add_attachment(
                content, maintype=maintype, subtype=subtype,
                filename=att.get('filename', 'file'),
            )

        recipients = []
        if isinstance(to, list):
            recipients.extend(to)
        else:
            recipients.append(to)
        if cc:
            recipients.extend(cc)
        if bcc:
            recipients.extend(bcc)

        if not recipients:
            return {'success': False, 'message': 'En az bir alıcı gerekli.'}

        raw_bytes = msg.as_bytes()
    except Exception as exc:
        logger.exception('send_mail prepare')
        return {'success': False, 'message': f'Mesaj hazırlanamadı: {exc}'}

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            _smtp_submit(
                smtp,
                account=account,
                password=password,
                msg=msg,
                recipients=recipients,
            )
        out = {'success': True, 'message_id': msg['Message-ID'], 'raw_message': raw_bytes}
        if password:
            try:
                from webmail.imap_client import append_message_to_sent, sync_folder_metadata

                sent_folder = append_message_to_sent(account, password, raw_bytes)
                sync_folder_metadata(account, password, sent_folder, limit=50)
                out['sent_folder'] = sent_folder
            except Exception as exc:
                err = str(exc)
                if hasattr(exc, 'args') and exc.args:
                    err = ' '.join(str(a) for a in exc.args if a)
                logger.warning('Sent klasörüne IMAP append başarısız: %s', err)
                out['sent_imap_warning'] = err
        return out
    except socket.gaierror as exc:
        hint = (
            f' SMTP hedefi çözülemedi ({host!r}). '
        )
        if not getattr(settings, 'IN_DOCKER', False):
            hint += (
                'Yerelde çalışıyorsanız kurulum sihirbazında mail adımını tamamlayın veya '
                'SMTP_HOST=127.0.0.1 (587 publish edilmiş olmalı).'
            )
        else:
            hint += (
                'Kurulum sihirbazı → Mail adımını çalıştırın veya SMTP_HOST ile Postfix konteyner adını verin; '
                'panel ile Postfix aynı Docker ağında olmalı (jir_network).'
            )
        return {'success': False, 'message': f'{exc}{hint}'}
    except ConnectionRefusedError:
        return {
            'success': False,
            'message': (
                f'{host}:{port} bağlantısı reddedildi. '
                f'Postfix konteyneri çalışıyor mu? (`docker ps | grep postfix`) '
                f'Host publish yoksa .env: SMTP_HOST=<köprü IP> veya kurulumda 587 host portunu '
                f'açıp jir_postfix\'i yeniden oluşturun. Docker IP: '
                f'`docker inspect jir_postfix --format "{{{{json .NetworkSettings.Networks}}}}"`'
            ),
        }
    except ssl.SSLError as exc:
        return {
            'success': False,
            'message': (
                f'SMTP TLS doğrulaması başarısız ({host}:{port}): {exc}. '
                'Mail kurulum adımını yeniden çalıştırın (dahili PKI).'
            ),
        }
    except smtplib.SMTPException as exc:
        # Python 3.12+: SMTPNotSupportedError aynı zamanda OSError alt sınıfıdır;
        # geniş OSError bloğunda yakalanıp yeniden fırlatılmamalı.
        if isinstance(exc, smtplib.SMTPNotSupportedError):
            return {
                'success': False,
                'message': (
                    f'SMTP komutu desteklenmiyor ({host}:{port}). '
                    'boky/postfix relay kullanıyorsanız gönderen domain ALLOWED_SENDER_DOMAINS '
                    'içinde olmalı; panel jir_network üzerinde olmalı. '
                    'Parola ile AUTH gerekiyorsa Postfix\'e SMTPD_SASL_USERS tanımlayın.'
                ),
            }
        return {'success': False, 'message': str(exc)}
    except OSError as exc:
        errno = getattr(exc, 'errno', None)
        if errno in (111, 61, 10061):
            return {
                'success': False,
                'message': (
                    f'{host}:{port} bağlantısı reddedildi (errno {errno}). '
                    'Postfix çalışıyor mu ve submission portu erişilebilir mi kontrol edin.'
                ),
            }
        return {'success': False, 'message': str(exc)}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}
