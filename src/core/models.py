"""Core models for spark-device-library."""

import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


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
