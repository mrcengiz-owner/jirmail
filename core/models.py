from django.db import models


class MailRole(models.TextChoices):
    FULL_ACCESS = 'FULL', 'Tam Erişim'
    SEND_ONLY = 'SEND', 'Sadece Gönderme'
    RECEIVE_ONLY = 'RECV', 'Sadece Alma'
    EXTERNAL_BLOCK = 'BLOCK', 'Şirket İçi'


class MailDomain(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class MailAccount(models.Model):
    domain = models.ForeignKey(MailDomain, on_delete=models.CASCADE)
    username = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    password_hash = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    quota_bytes = models.BigIntegerField(default=52428800, help_text="Kota bayt cinsinden (50MB = 52428800, 0 = sınırsız)")
    role = models.CharField(max_length=10, choices=MailRole.choices, default=MailRole.FULL_ACCESS)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Mail Hesabı'
        verbose_name_plural = 'Mail Hesapları'

    def __str__(self):
        return self.email

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