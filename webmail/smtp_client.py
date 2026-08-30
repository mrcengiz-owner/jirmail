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
from email.utils import formataddr, formatdate, make_msgid

from django.conf import settings

from management.mail_service_endpoint import resolve_mail_endpoint
from management.mail_tls import (
    heal_mail_tls_pki,
    invalidate_mail_tls_ca_cache,
    smtp_starttls_required,
    smtp_tls_context,
)
from webmail.recipients import parse_recipient_list


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
    raw_bytes: bytes,
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
    smtp.sendmail(account.email, recipients, raw_bytes)


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

        if isinstance(to, list):
            to_addrs = parse_recipient_list(', '.join(to))
        else:
            to_addrs = parse_recipient_list(str(to or ''))
        cc_addrs = parse_recipient_list(', '.join(cc)) if cc else []
        bcc_addrs = parse_recipient_list(', '.join(bcc)) if bcc else []

        msg = EmailMessage()
        display = (getattr(account, 'username', '') or '').strip()
        if not display and '@' in account.email:
            display = account.email.split('@')[0].replace('.', ' ').replace('_', ' ').title()
        msg['From'] = formataddr((display or account.email, account.email))
        msg['To'] = ', '.join(to_addrs)
        if cc_addrs:
            msg['Cc'] = ', '.join(cc_addrs)
        # Bcc yalnızca SMTP envelope'da — başlığa yazma (gizlilik + spam skoru)
        msg['Subject'] = subject or ''
        msg['Message-ID'] = make_msgid(domain=_message_id_domain(account))
        msg['Date'] = formatdate(localtime=True)

        body = body_text or ''
        signature = (getattr(account, 'signature', '') or '').strip()
        if signature and signature not in body:
            body = f'{body.rstrip()}\n\n--\n{signature}' if body.strip() else signature

        if body_html:
            html = body_html
            if signature and signature not in html:
                sig_html = signature.replace('\n', '<br>\n')
                html = f'{html}<br><br>--<br>{sig_html}'
            msg.set_content(body)
            msg.add_alternative(html, subtype='html')
        else:
            msg.set_content(body)

        for att in (attachments or []):
            content = att.get('content', b'')
            maintype, _, subtype = (att.get('mime_type') or 'application/octet-stream').partition('/')
            msg.add_attachment(
                content, maintype=maintype, subtype=subtype,
                filename=att.get('filename', 'file'),
            )

        recipients = list(to_addrs)
        recipients.extend(cc_addrs)
        recipients.extend(bcc_addrs)

        if not recipients:
            return {'success': False, 'message': 'En az bir alıcı gerekli.'}

        raw_bytes = msg.as_bytes()
        from webmail.dkim_sign import sign_message_bytes

        raw_bytes, dkim_status = sign_message_bytes(raw_bytes, account)
        if dkim_status.get('required') and not dkim_status.get('signed'):
            reason = dkim_status.get('reason') or 'DKIM imzalanamadı'
            return {
                'success': False,
                'message': (
                    f'Gönderim iptal: {reason}. '
                    'Panel → Domainler → DNS kayıtlarını doğrulayın (SPF, DKIM, DMARC).'
                ),
                'dkim': dkim_status,
            }
    except Exception as exc:
        logger.exception('send_mail prepare')
        return {'success': False, 'message': f'Mesaj hazırlanamadı: {exc}'}

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            _smtp_submit(
                smtp,
                account=account,
                password=password,
                raw_bytes=raw_bytes,
                recipients=recipients,
            )
        # raw_bytes yalnızca IMAP Sent append için; API JSON yanıtına eklenmez (bytes → 500).
        out = {'success': True, 'message_id': msg['Message-ID'], 'dkim': dkim_status}
        if dkim_status.get('required') and dkim_status.get('signed'):
            out['message'] = 'Gönderildi (DKIM imzalı).'
        elif not dkim_status.get('required'):
            out.setdefault('warnings', []).append(
                'DKIM yapılandırılmadı — alıcı spam klasörüne düşebilir. DNS kayıtlarını tamamlayın.'
            )
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
    except ssl.SSLError as exc:
        # 1) Volume CA'ya geç  2) gerekirse PKI yenile + Postfix reload
        logger.warning('SMTP TLS başarısız, onarım deneniyor: %s', exc)
        invalidate_mail_tls_ca_cache()
        try:
            with smtplib.SMTP(host, port, timeout=30) as smtp:
                _smtp_submit(
                    smtp,
                    account=account,
                    password=password,
                    raw_bytes=raw_bytes,
                    recipients=recipients,
                )
            out = {'success': True, 'message_id': msg['Message-ID'], 'dkim': dkim_status, 'tls_healed': True}
            if dkim_status.get('required') and dkim_status.get('signed'):
                out['message'] = 'Gönderildi (DKIM imzalı).'
            return out
        except ssl.SSLError:
            heal = heal_mail_tls_pki(force_regen=True)
            try:
                with smtplib.SMTP(host, port, timeout=30) as smtp:
                    _smtp_submit(
                        smtp,
                        account=account,
                        password=password,
                        raw_bytes=raw_bytes,
                        recipients=recipients,
                    )
                out = {
                    'success': True,
                    'message_id': msg['Message-ID'],
                    'dkim': dkim_status,
                    'tls_healed': True,
                    'heal': heal,
                }
                if dkim_status.get('required') and dkim_status.get('signed'):
                    out['message'] = 'Gönderildi (DKIM imzalı; TLS onarıldı).'
                return out
            except Exception as retry_exc:
                return {
                    'success': False,
                    'message': (
                        f'SMTP TLS doğrulaması başarısız ({host}:{port}): {retry_exc}. '
                        f'PKI onarım denendi ({heal.get("ok")}). '
                        'Postfix/Dovecot yeniden başlatın: docker compose restart postfix dovecot django'
                    ),
                    'heal': heal,
                }
        except Exception as retry_exc:
            return {
                'success': False,
                'message': (
                    f'SMTP TLS doğrulaması başarısız ({host}:{port}): {retry_exc}. '
                    'Mail kurulum adımını yeniden çalıştırın (dahili PKI).'
                ),
            }
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
