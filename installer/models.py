from django.db import models
import uuid


class InstallationRun(models.Model):
    """Tek bir kurulum çalışmasını (run) temsil eder.

    Setup wizard 'Sistemi Mühürle' butonuna basıldığında bir run oluşur ve
    tüm orkestratör adımları bu run altında gruplanır.
    """
    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('running', 'Çalışıyor'),
        ('completed', 'Tamamlandı'),
        ('failed', 'Başarısız'),
        ('cancelled', 'İptal Edildi'),
    ]

    run_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    config_snapshot = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-started_at']
        verbose_name = 'Kurulum Çalışması'
        verbose_name_plural = 'Kurulum Çalışmaları'

    def __str__(self):
        return f'Run {self.run_id} ({self.status})'


class InstallationStep(models.Model):
    """Kurulum sırasında yürütülen tek bir adım.

    Örnek: image pull, network create, container start, migrate, vs.
    """
    STATUS_CHOICES = [
        ('pending', 'Beklemede'),
        ('running', 'Çalışıyor'),
        ('completed', 'Tamamlandı'),
        ('failed', 'Başarısız'),
        ('skipped', 'Atlandı'),
    ]

    run = models.ForeignKey(InstallationRun, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=200)
    description = models.CharField(max_length=500, blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    log = models.TextField(blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    progress_percent = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'id']
        verbose_name = 'Kurulum Adımı'
        verbose_name_plural = 'Kurulum Adımları'

    def __str__(self):
        return f'{self.order}. {self.name} ({self.status})'

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None
