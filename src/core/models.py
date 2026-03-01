"""Core models for spark-device-library."""

import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from model_utils.models import TimeStampedModel


class User(AbstractUser):
    """Custom user model with UUID primary key and role-based access."""

    class Role(models.TextChoices):
        VIEWER = "viewer", "Viewer"
        EDITOR = "editor", "Editor"
        ADMIN = "admin", "Admin"

    ROLE_HIERARCHY: dict[str, int] = {
        Role.VIEWER: 0,
        Role.EDITOR: 1,
        Role.ADMIN: 2,
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)

    class Meta:
        ordering = ["username"]

    def __str__(self):
        return self.email or self.username

    def has_role(self, minimum_role: str) -> bool:
        """Check if user has at least the given role level."""
        return self.ROLE_HIERARCHY.get(self.role, 0) >= self.ROLE_HIERARCHY.get(minimum_role, 0)

    @property
    def is_admin_role(self) -> bool:
        return self.has_role(self.Role.ADMIN)

    @property
    def is_editor(self) -> bool:
        return self.has_role(self.Role.EDITOR)


class Invitation(TimeStampedModel):
    """Invitation to join the platform."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField()
    role = models.CharField(max_length=20, choices=User.Role.choices, default=User.Role.VIEWER)
    token = models.CharField(max_length=128, unique=True, default=secrets.token_urlsafe)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitation_accepted",
    )
    revoked = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"Invitation for {self.email} ({self.get_role_display()})"

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def is_valid(self) -> bool:
        return not self.revoked and not self.accepted_at and self.expires_at > timezone.now()

    @property
    def status(self) -> str:
        if self.accepted_at:
            return "accepted"
        if self.revoked:
            return "revoked"
        if self.expires_at <= timezone.now():
            return "expired"
        return "pending"
