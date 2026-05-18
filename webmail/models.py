"""Webmail için DB cache modelleri.

Mail body'leri DB'de tutmuyoruz — yalnızca metadata cache'liyoruz, body
istek anında IMAP'tan fetch edilir. Bu yaklaşım hem disk kullanımını düşürür
hem de IMAP source-of-truth olarak kalır.
"""
from __future__ import annotations

from django.db import models

from core.models import MailAccount


class MailFolder(models.Model):
    """IMAP klasör metadata'sı (INBOX, Sent, Drafts, ...)."""
    account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name='folders')
    name = models.CharField(max_length=255)
    display_name = models.CharField(max_length=255, blank=True, default='')
    uidvalidity = models.BigIntegerField(default=0)
    uidnext = models.BigIntegerField(default=0)
    total = models.PositiveIntegerField(default=0)
    unread = models.PositiveIntegerField(default=0)
    last_synced = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [('account', 'name')]
        ordering = ['name']

    def __str__(self):
        return f'{self.account.email} / {self.name}'


class MailMessageCache(models.Model):
    """IMAP mesajının metadata cache'i.

    Body'nin kendisi burada saklanmaz; gerektiğinde IMAP'tan fetch edilir.
    UID + uidvalidity + folder kombinasyonu unique kimliği oluşturur.
    """
    folder = models.ForeignKey(MailFolder, on_delete=models.CASCADE, related_name='messages')
    uid = models.PositiveIntegerField()
    message_id = models.CharField(max_length=512, blank=True, default='', db_index=True)
    subject = models.CharField(max_length=998, blank=True, default='')
    from_addr = models.CharField(max_length=500, blank=True, default='')
    from_name = models.CharField(max_length=255, blank=True, default='')
    sender_meta = models.JSONField(default=dict, blank=True)
    to_addr = models.TextField(blank=True, default='')
    cc_addr = models.TextField(blank=True, default='')
    date = models.DateTimeField(null=True, blank=True, db_index=True)

    flags = models.JSONField(default=list, blank=True)
    is_seen = models.BooleanField(default=False, db_index=True)
    is_flagged = models.BooleanField(default=False, db_index=True)
    is_answered = models.BooleanField(default=False)
    is_draft = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    has_attachments = models.BooleanField(default=False)
    snippet = models.CharField(max_length=500, blank=True, default='')
    raw_size = models.PositiveIntegerField(default=0)

    fetched_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [('folder', 'uid')]
        ordering = ['-date', '-uid']
        indexes = [
            models.Index(fields=['folder', '-date']),
            models.Index(fields=['folder', '-uid']),
        ]

    def __str__(self):
        return f'{self.folder.name}/{self.uid}: {self.subject[:60]}'


class MailAttachmentMeta(models.Model):
    """Attachment metadata (header bilgisi). Asıl içerik on-demand IMAP'tan."""
    message = models.ForeignKey(MailMessageCache, on_delete=models.CASCADE, related_name='attachments')
    part_id = models.CharField(max_length=50)
    filename = models.CharField(max_length=500, blank=True, default='')
    mime_type = models.CharField(max_length=255, blank=True, default='')
    size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['part_id']

    def __str__(self):
        return f'{self.filename or self.part_id} ({self.mime_type})'


class MailOutboundLog(models.Model):
    """Gönderilen iletiler — SMTP/IMAP kaydı (webmail ve dashboard istatistik)."""

    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_DEFERRED = 'deferred'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Beklemede'),
        (STATUS_SENT, 'Gönderildi'),
        (STATUS_FAILED, 'Başarısız'),
        (STATUS_DEFERRED, 'Ertelendi'),
    ]

    account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name='outbound_logs')
    to_addr = models.TextField()
    subject = models.CharField(max_length=998, blank=True, default='')
    snippet = models.CharField(max_length=500, blank=True, default='')
    message_id = models.CharField(max_length=512, blank=True, default='', db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.account.email} → {self.to_addr[:40]} ({self.status})'


class ScheduledMail(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Beklemede'),
        (STATUS_SENT, 'Gönderildi'),
        (STATUS_FAILED, 'Başarısız'),
        (STATUS_CANCELLED, 'İptal'),
    ]

    account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name='scheduled_mails')
    to_addr = models.TextField()
    cc_addr = models.TextField(blank=True, default='')
    bcc_addr = models.TextField(blank=True, default='')
    subject = models.CharField(max_length=998, blank=True, default='')
    body_text = models.TextField(blank=True, default='')
    body_html = models.TextField(blank=True, default='')
    attachments_meta = models.JSONField(default=list, blank=True)
    send_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['send_at']

    def __str__(self):
        return f'{self.account.email} @ {self.send_at} ({self.status})'
