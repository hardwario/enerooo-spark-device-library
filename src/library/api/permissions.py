"""API permissions for the device library."""

from django.utils import timezone
from rest_framework import permissions

from library.models import APIKey


class HasAPIKey(permissions.BasePermission):
    """Allow access via X-API-Key header."""

    def has_permission(self, request, view):
        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            return False

        try:
            key_obj = APIKey.objects.get(key=api_key, is_active=True)
            key_obj.last_used_at = timezone.now()
            key_obj.save(update_fields=["last_used_at"])
            return True
        except APIKey.DoesNotExist:
            return False


class IsAPIKeyOrSessionAuth(permissions.BasePermission):
    """Allow access via API key or authenticated session."""

    def has_permission(self, request, view):
        # Check API key first
        api_key = request.headers.get("X-API-Key", "")
        if api_key:
            try:
                key_obj = APIKey.objects.get(key=api_key, is_active=True)
                key_obj.last_used_at = timezone.now()
                key_obj.save(update_fields=["last_used_at"])
                return True
            except APIKey.DoesNotExist:
                return False

        # Fall back to session auth
        return request.user and request.user.is_authenticated


class IsEditorOrAdmin(permissions.BasePermission):
    """Allow access only to users with editor or admin role."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_editor
