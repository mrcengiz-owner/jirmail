"""SMTP submission istemcisi.

Kullanıcı kendi mail hesabıyla SMTP submission portu (587, STARTTLS) üzerinden
Postfix'e bağlanır. SASL auth ile mail gönderir.
"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from django.conf import settings


def send_mail(account, password: str, *, to: list[str] | str, subject: str, body_text: str,
              body_html: str = '', cc: list[str] | None = None, bcc: list[str] | None = None,
              attachments: list[dict] | None = None) -> dict:
    """Postfix submission portu (587) üzerinden mail gönderir.

    attachments: [{'filename': 'a.pdf', 'mime_type': 'application/pdf', 'content': bytes}]
    """
    host = getattr(settings, 'SMTP_HOST', 'jir_postfix')
    port = int(getattr(settings, 'SMTP_PORT', 587))

    msg = EmailMessage()
    msg['From'] = formataddr((account.email.split('@')[0], account.email))
    msg['To'] = ', '.join(to) if isinstance(to, list) else to
    if cc:
        msg['Cc'] = ', '.join(cc)
    msg['Subject'] = subject
    msg['Message-ID'] = make_msgid(domain=account.domain.name)

    msg.set_content(body_text or '')
    if body_html:
        msg.add_alternative(body_html, subtype='html')

    for att in (attachments or []):
        content = att.get('content', b'')
        maintype, _, subtype = (att.get('mime_type') or 'application/octet-stream').partition('/')
        msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=att.get('filename', 'file'))

    recipients = []
    if isinstance(to, list):
        recipients.extend(to)
    else:
        recipients.append(to)
    if cc:
        recipients.extend(cc)
    if bcc:
        recipients.extend(bcc)

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            try:
                smtp.starttls()
                smtp.ehlo()
            except smtplib.SMTPNotSupportedError:
                pass
            smtp.login(account.email, password)
            smtp.send_message(msg, from_addr=account.email, to_addrs=recipients)
        return {'success': True, 'message_id': msg['Message-ID']}
    except Exception as exc:
        return {'success': False, 'message': str(exc)}
