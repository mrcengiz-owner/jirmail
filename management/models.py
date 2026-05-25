from django.db import models


class MailRepairRun(models.Model):
    """Dashboard onarım işlemi audit kaydı."""

    action = models.CharField(max_length=64, db_index=True)
    actor_email = models.CharField(max_length=254, blank=True, default='')
    ok = models.BooleanField(default=False)
    summary = models.CharField(max_length=500, blank=True, default='')
    report = models.JSONField(default=dict, blank=True)
    ip_address = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Mail onarım kaydı'
        verbose_name_plural = 'Mail onarım kayıtları'

    def __str__(self) -> str:
        mark = 'OK' if self.ok else 'FAIL'
        return f'{self.action} [{mark}] {self.created_at:%Y-%m-%d %H:%M}'
