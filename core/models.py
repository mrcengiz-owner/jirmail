from django.db import models
import secrets


class MailRole(models.TextChoices):
    FULL_ACCESS = 'FULL', 'Süper Yönetici'
    WEBMAIL_USER = 'USER', 'Webmail Kullanıcısı'
    SEND_ONLY = 'SEND', 'Sadece Gönderme'
    RECEIVE_ONLY = 'RECV', 'Sadece Alma'
    EXTERNAL_BLOCK = 'BLOCK', 'Şirket İçi'


class MailDomain(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    dkim_enabled = models.BooleanField(default=False)
    dkim_private_key = models.TextField(blank=True, default='')
    dkim_public_key = models.TextField(blank=True, default='')
    spf_record = models.CharField(max_length=255, blank=True, default='')
    dkim_record = models.CharField(max_length=510, blank=True, default='')
    dmarc_record = models.CharField(max_length=255, blank=True, default='')
    verification_status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Beklemede'),
        ('verified', 'Doğrulanmış'),
        ('failed', 'Başarısız')
    ])
    verified_at = models.DateTimeField(null=True, blank=True)

    DNS_PROVIDER_CHOICES = [
        ('manual', 'Manuel'),
        ('cloudflare', 'Cloudflare'),
        ('route53', 'AWS Route53'),
        ('namecheap', 'Namecheap'),
    ]
    dns_provider = models.CharField(max_length=20, choices=DNS_PROVIDER_CHOICES, default='manual')
    dns_credentials = models.JSONField(default=dict, blank=True, help_text='Provider API token/secret (encrypted-at-rest önerilir)')
    tls_cert_path = models.CharField(max_length=500, blank=True, default='')
    tls_key_path = models.CharField(max_length=500, blank=True, default='')
    tls_issued_at = models.DateTimeField(null=True, blank=True)
    tls_expires_at = models.DateTimeField(null=True, blank=True)

    ai_enabled = models.BooleanField(default=False, help_text='Domain için AI asistan')
    ai_provider = models.CharField(max_length=32, default='openrouter')
    ai_default_model = models.CharField(max_length=128, blank=True, default='openai/gpt-4o-mini')
    ai_system_prompt_default = models.TextField(
        blank=True,
        default='Sen profesyonel bir e-posta asistanısın. Türkçe, kısa ve net yaz.',
    )

    class Meta:
        ordering = ['name']

    @property
    def ai_available(self) -> bool:
        return self.is_active and self.ai_enabled

    def __str__(self):
        return self.name

    def generate_dkim_keys(self):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.backends import default_backend

        key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=2048,
            backend=default_backend()
        )
        private_key = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode()

        public_key = key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

        selector = f"mail-{secrets.token_hex(4)}"
        public_key_dns = public_key.replace('-----BEGIN PUBLIC KEY-----', '').replace('-----END PUBLIC KEY-----', '').replace('\n', '')

        self.dkim_private_key = private_key
        self.dkim_public_key = public_key
        self.dkim_record = f"{selector}._domainkey.{self.name} IN TXT \"v=DKIM1; k=rsa; p={public_key_dns}\""
        self.spf_record = f"v=spf1 mx a:mail.{self.name} -all"
        self.dmarc_record = f"v=DMARC1; p=quarantine; rua=mailto:dmarc@{self.name}"
        self.dkim_enabled = True
        self.verification_status = 'pending'
        self.save()

        return {
            'dkim_selector': selector,
            'spf_record': self.spf_record,
            'dkim_record': self.dkim_record,
            'dmarc_record': self.dmarc_record
        }


class MailAccount(models.Model):
    domain = models.ForeignKey(MailDomain, on_delete=models.CASCADE)
    username = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    quota_bytes = models.BigIntegerField(default=52428800, help_text="Kota bayt cinsinden (50MB = 52428800, 0 = sınırsız)")
    role = models.CharField(max_length=10, choices=MailRole.choices, default=MailRole.WEBMAIL_USER)

    signature = models.TextField(blank=True, default='', help_text="Email imzası")
    auto_responder_enabled = models.BooleanField(default=False)
    auto_responder_subject = models.CharField(max_length=255, blank=True, default='')
    auto_responder_body = models.TextField(blank=True, default='')
    forward_to = models.EmailField(blank=True, default='', help_text="Yönlendirme adresi")
    forward_enabled = models.BooleanField(default=False)
    keep_copy = models.BooleanField(default=True, help_text="Yönlendirme yaparken kopyayı sakla")

    ai_enabled = models.BooleanField(default=False)
    ai_provider = models.CharField(max_length=32, blank=True, default='')
    ai_model = models.CharField(max_length=128, blank=True, default='')
    ai_api_key = models.CharField(max_length=512, blank=True, default='')
    ai_system_prompt = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Mail Hesabı'
        verbose_name_plural = 'Mail Hesapları'

    def __str__(self):
        return self.email

    @property
    def can_access_panel(self) -> bool:
        from jir_core.permissions import can_access_panel
        return can_access_panel(self.role)

    def is_bootstrap_admin(self) -> bool:
        """Kurulum sırasında oluşturulan ilk süper yönetici hesabı."""
        try:
            from saas.models import SystemConfig
            cfg = SystemConfig.objects.first()
            bootstrap = (getattr(cfg, 'bootstrap_admin_email', None) or '').strip().lower()
            if bootstrap:
                return self.email.lower() == bootstrap
        except Exception:
            pass
        return False

    def permissions_summary(self) -> dict:
        from jir_core.permissions import role_permissions
        data = role_permissions(self.role)
        data['is_superuser'] = self.is_bootstrap_admin()
        return data

    @property
    def ai_available(self) -> bool:
        if not self.is_active or not self.ai_enabled:
            return False
        return bool((self.ai_api_key or '').strip())

    @property
    def quota_mb(self):
        if self.quota_bytes == 0:
            return 'Sınırsız'
        return round(self.quota_bytes / (1024 * 1024), 1)

    @property
    def current_storage_bytes(self):
        import os
        mail_path = f"/var/mail/vhosts/{self.domain.name}/{self.username}"
        if os.path.exists(mail_path):
            total = 0
            for dirpath, dirnames, filenames in os.walk(mail_path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    total += os.path.getsize(fp)
            return total
        return 0

    @property
    def storage_used_mb(self):
        return round(self.current_storage_bytes / (1024 * 1024), 2)


class Backup(models.Model):
    BACKUP_TYPES = [
        ('full', 'Tam Yedekleme'),
        ('incremental', 'Artımlı Yedekleme'),
        ('config', 'Konfigürasyon'),
        ('emails', 'E-postalar'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('running', 'Çalışıyor'),
        ('completed', 'Tamamlandı'),
        ('failed', 'Başarısız'),
    ]

    name = models.CharField(max_length=255)
    backup_type = models.CharField(max_length=20, choices=BACKUP_TYPES, default='full')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    file_path = models.CharField(max_length=500, blank=True, default='')
    file_size_mb = models.FloatField(default=0)
    includes_emails = models.BooleanField(default=False)
    includes_configs = models.BooleanField(default=False)
    includes_database = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    scheduled_for = models.DateTimeField(null=True, blank=True)
    is_auto_backup = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Yedekleme'
        verbose_name_plural = 'Yedeklemeler'

    def __str__(self):
        return f"{self.name} ({self.backup_type}) - {self.status}"