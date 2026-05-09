from django.db import models
import uuid

class SubscriptionTier(models.TextChoices):
    FREE = 'FREE', 'Free (3 Accounts)'
    PRO = 'PRO', 'Pro (50 Accounts)'
    ENTERPRISE = 'ENT', 'Enterprise (Unlimited)'

class SystemConfig(models.Model):
    instance_id = models.UUIDField(default=uuid.uuid4, unique=True)
    is_installed = models.BooleanField(default=False)
    jir_local_key = models.CharField(max_length=64, blank=True, null=True)

    hq_verified = models.BooleanField(default=False)
    hq_api_key = models.CharField(max_length=255, blank=True, null=True)

    tier = models.CharField(
        max_length=10,
        choices=SubscriptionTier.choices,
        default=SubscriptionTier.FREE
    )
    max_accounts = models.PositiveIntegerField(default=3)
    storage_limit_gb = models.PositiveIntegerField(default=1)

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.tier} - {self.instance_id}"