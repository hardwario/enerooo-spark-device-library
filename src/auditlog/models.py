"""Audit log models."""

import uuid

from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel


class AuditLog(TimeStampedModel):
    """Tracks user actions across the system."""

    class Category(models.TextChoices):
        DEVICE = "device", "Device"
        VENDOR = "vendor", "Vendor"
        VERSION = "version", "Version"
        APIKEY = "apikey", "API Key"
        IMPORT = "import", "Import"
        EXPORT = "export", "Export"
        USER = "user", "User"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    category = models.CharField(max_length=20, choices=Category.choices)
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=50)
    target_id = models.UUIDField(null=True, blank=True)
    target_label = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]
        indexes = [
            models.Index(fields=["-created"]),
            models.Index(fields=["category"]),
            models.Index(fields=["user", "-created"]),
        ]

    def __str__(self):
        return f"{self.user} {self.action} {self.target_type} {self.target_label}"
