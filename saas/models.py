from django.db import models
import uuid

class SubscriptionTier(models.TextChoices):
    FREE = 'FREE', 'Free (3 Accounts)'
    PRO = 'PRO', 'Pro (50 Accounts)'
    ENTERPRISE = 'ENT', 'Enterprise (Unlimited)'

class SystemConfig(models.Model):
    DB_ENGINE_CHOICES = [
        ('django.db.backends.sqlite3', 'SQLite'),
        ('django.db.backends.postgresql', 'PostgreSQL'),
    ]

    instance_id = models.UUIDField(default=uuid.uuid4, unique=True)
    is_installed = models.BooleanField(default=False)
    jir_local_key = models.CharField(max_length=64, blank=True, null=True)

    db_engine = models.CharField(
        max_length=50,
        choices=DB_ENGINE_CHOICES,
        default='django.db.backends.sqlite3'
    )
    db_host = models.CharField(max_length=255, blank=True, default='localhost')
    db_port = models.PositiveIntegerField(default=5432, null=True, blank=True)
    db_name = models.CharField(max_length=255, blank=True, default='')
    db_user = models.CharField(max_length=255, blank=True, default='')
    db_password = models.CharField(max_length=255, blank=True, default='')

    mail_data_path = models.CharField(max_length=500, blank=True, default='/var/mail/vhosts')
    postfix_vmail_path = models.CharField(max_length=500, blank=True, default='/etc/postfix/vmail_accounts')
    dovecot_passdb_path = models.CharField(max_length=500, blank=True, default='/etc/dovecot/userdb')
    backup_dir = models.CharField(max_length=500, blank=True, default='/var/backups/jirmail')

    hq_verified = models.BooleanField(default=False)
    hq_api_key = models.CharField(max_length=255, blank=True, null=True)

    tier = models.CharField(
        max_length=10,
        choices=SubscriptionTier.choices,
        default=SubscriptionTier.FREE
    )
    max_accounts = models.PositiveIntegerField(default=3)
    storage_limit_gb = models.PositiveIntegerField(default=1)

    installation_log = models.JSONField(default=dict, blank=True)

    # Coolify vb.: gerçek Docker konteyner adları (postfix, dovecot, … anahtarları)
    docker_container_map = models.JSONField(
        default=dict,
        blank=True,
        help_text='Örn. {"postfix":"stack-postfix-abc","dovecot":"stack-dovecot-xyz"}',
    )

    updated_at = models.DateTimeField(auto_now=True)

    def get_database_config(self):
        if self.db_engine == 'django.db.backends.postgresql':
            return {
                'ENGINE': self.db_engine,
                'NAME': self.db_name or 'jir_mail',
                'USER': self.db_user or 'postgres',
                'PASSWORD': self.db_password,
                'HOST': self.db_host or 'localhost',
                'PORT': self.db_port or 5432,
                'ATOMIC_REQUESTS': False,
                'AUTOCOMMIT': True,
                'CONN_MAX_AGE': 600,
                'OPTIONS': {},
            }
        else:
            from pathlib import Path
            return {
                'ENGINE': 'django.db.backends.sqlite3',
                'NAME': Path(__file__).resolve().parent.parent / 'db.sqlite3',
                'ATOMIC_REQUESTS': False,
                'AUTOCOMMIT': True,
                'CONN_MAX_AGE': 600,
                'OPTIONS': {},
            }

    def verify_installation(self):
        """Verify and return installation status from database."""
        self.refresh_from_db()
        return self.is_installed

    def __str__(self):
        return f"{self.tier} - {self.instance_id}"


class Alert(models.Model):
    SEVERITY_CHOICES = [
        ('info', 'Bilgi'),
        ('warning', 'Uyarı'),
        ('error', 'Hata'),
        ('critical', 'Kritik'),
    ]

    CATEGORY_CHOICES = [
        ('system', 'Sistem'),
        ('disk', 'Disk'),
        ('memory', 'Bellek'),
        ('cpu', 'CPU'),
        ('database', 'Veritabanı'),
        ('mail', 'Mail Servisi'),
        ('security', 'Güvenlik'),
        ('backup', 'Yedekleme'),
    ]

    title = models.CharField(max_length=255)
    message = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='info')
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='system')
    is_read = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    threshold_value = models.CharField(max_length=50, blank=True, default='')
    current_value = models.CharField(max_length=50, blank=True, default='')

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Uyarı'
        verbose_name_plural = 'Uyarılar'

    def __str__(self):
        return f"[{self.severity}] {self.title}"


class AlertThreshold(models.Model):
    METRIC_CHOICES = [
        ('disk_usage', 'Disk Kullanımı %'),
        ('memory_usage', 'Bellek Kullanımı %'),
        ('cpu_usage', 'CPU Kullanımı %'),
        ('mail_queue', 'Mail Kuyruğu'),
        ('failed_logins', 'Başarısız Girişler'),
        ('storage_quota', 'Depolama Kotası %'),
    ]

    name = models.CharField(max_length=100)
    metric = models.CharField(max_length=30, choices=METRIC_CHOICES)
    warning_threshold = models.FloatField(default=70.0)
    critical_threshold = models.FloatField(default=90.0)
    is_enabled = models.BooleanField(default=True)
    check_interval_minutes = models.PositiveIntegerField(default=5)
    last_check = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['metric']
        verbose_name = 'Uyarı Eşiği'
        verbose_name_plural = 'Uyarı Eşikleri'

    def __str__(self):
        return f"{self.name} ({self.metric})"