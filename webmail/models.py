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
    ai_meta = models.JSONField(default=dict, blank=True, help_text='AI triage: category, priority, summary…')

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


class MailAiTask(models.Model):
    """Kullanıcının AI asistanına verdiği arka plan görevleri."""

    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_DONE = 'done'
    STATUS_FAILED = 'failed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_PENDING, 'Beklemede'),
        (STATUS_RUNNING, 'Çalışıyor'),
        (STATUS_DONE, 'Tamamlandı'),
        (STATUS_FAILED, 'Başarısız'),
        (STATUS_CANCELLED, 'İptal'),
    ]

    TYPE_CHAT = 'chat'
    TYPE_ANALYZE = 'analyze'
    TYPE_SEND = 'send'
    TYPE_REPLY = 'reply'
    TYPE_CUSTOM = 'custom'

    TYPE_CHOICES = [
        (TYPE_CHAT, 'Sohbet'),
        (TYPE_ANALYZE, 'Analiz'),
        (TYPE_SEND, 'Gönder'),
        (TYPE_REPLY, 'Yanıt'),
        (TYPE_CUSTOM, 'Özel'),
    ]

    account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name='ai_tasks')
    instruction = models.TextField()
    task_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_CUSTOM, db_index=True)
    context = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'AI#{self.id} {self.task_type} ({self.status})'


class MailAgentProfile(models.Model):
    """Hesap bazlı AI posta ajanı tercihleri."""

    MODE_OFF = 'off'
    MODE_ASSIST = 'assist'
    MODE_AUTOPILOT = 'autopilot'
    MODE_CHOICES = [
        (MODE_OFF, 'Kapalı'),
        (MODE_ASSIST, 'Asistan (öneri)'),
        (MODE_AUTOPILOT, 'Otopilot (güvenli aksiyonlar)'),
    ]

    DIGEST_DAILY = 'daily'
    DIGEST_WEEKLY = 'weekly'
    DIGEST_CHOICES = [
        (DIGEST_DAILY, 'Günlük'),
        (DIGEST_WEEKLY, 'Haftalık'),
    ]

    account = models.OneToOneField(MailAccount, on_delete=models.CASCADE, related_name='agent_profile')
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_ASSIST, db_index=True)
    auto_triage = models.BooleanField(default=True)
    auto_organize = models.BooleanField(default=True)
    auto_reply_suggest = models.BooleanField(default=True)
    digest_enabled = models.BooleanField(default=True)
    digest_frequency = models.CharField(max_length=16, choices=DIGEST_CHOICES, default=DIGEST_DAILY)
    digest_hour = models.PositiveSmallIntegerField(default=8, help_text='UTC saat (0-23)')
    triage_batch_size = models.PositiveSmallIntegerField(default=15)
    organize_batch_size = models.PositiveSmallIntegerField(default=25)
    last_triage_at = models.DateTimeField(null=True, blank=True)
    last_organize_at = models.DateTimeField(null=True, blank=True)
    last_digest_at = models.DateTimeField(null=True, blank=True)
    last_digest_text = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'Agent {self.account.email} ({self.mode})'


class MailAiRule(models.Model):
    """Kullanıcı / AI posta kuralları."""

    ACTION_SPAM = 'spam'
    ACTION_ARCHIVE = 'archive'
    ACTION_MARK_READ = 'mark_read'
    ACTION_MOVE = 'move_folder'
    ACTION_STAR = 'star'
    ACTION_DELETE = 'delete'
    ACTION_CHOICES = [
        (ACTION_SPAM, 'Spam'),
        (ACTION_ARCHIVE, 'Arşivle'),
        (ACTION_MARK_READ, 'Okundu işaretle'),
        (ACTION_MOVE, 'Klasöre taşı'),
        (ACTION_STAR, 'Yıldızla'),
        (ACTION_DELETE, 'Sil'),
    ]

    account = models.ForeignKey(MailAccount, on_delete=models.CASCADE, related_name='ai_rules')
    name = models.CharField(max_length=120)
    enabled = models.BooleanField(default=True, db_index=True)
    priority = models.PositiveSmallIntegerField(default=100, db_index=True)
    match_from = models.CharField(max_length=255, blank=True, default='')
    match_subject = models.CharField(max_length=255, blank=True, default='')
    match_category = models.CharField(max_length=32, blank=True, default='')
    action_type = models.CharField(max_length=32, choices=ACTION_CHOICES, default=ACTION_ARCHIVE)
    action_target = models.CharField(max_length=255, blank=True, default='', help_text='move_folder için hedef')
    created_by_ai = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['priority', 'id']

    def __str__(self):
        return f'{self.name} → {self.action_type}'
