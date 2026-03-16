"""API permissions for the device library."""

import hashlib
import hmac
import time

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


class HasHMACSignature(permissions.BasePermission):
    """Allow access via HMAC-SHA256 signed requests.

    The client signs `{timestamp}.{method}.{path}` with the API key secret
    and sends X-API-Key-Id, X-Timestamp, and X-Signature headers.
    """

    MAX_SKEW_SECONDS = 300  # ±5 minutes

    def has_permission(self, request, view):
        key_id = request.headers.get("X-API-Key-Id", "")
        timestamp = request.headers.get("X-Timestamp", "")
        signature = request.headers.get("X-Signature", "")

        if not key_id or not timestamp or not signature:
            return False

        # Validate timestamp format and replay window
        try:
            ts = int(timestamp)
        except (ValueError, TypeError):
            return False

        if abs(time.time() - ts) > self.MAX_SKEW_SECONDS:
            return False

        # Look up active API key by UUID
        try:
            key_obj = APIKey.objects.get(pk=key_id, is_active=True)
        except (APIKey.DoesNotExist, ValueError):
            return False

        # Reconstruct the signed message and verify
        message = f"{timestamp}.{request.method}.{request.path}"
        expected = hmac.new(
            key_obj.key.encode(),
            message.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            return False

        key_obj.last_used_at = timezone.now()
        key_obj.save(update_fields=["last_used_at"])
        return True


class HasBootstrapToken(permissions.BasePermission):
    """Allow access via a shared bootstrap token in the X-Bootstrap-Token header."""

    def has_permission(self, request, view):
        from django.conf import settings

        token = settings.GATEWAY_BOOTSTRAP_TOKEN
        if not token:
            return False

        provided = request.headers.get("X-Bootstrap-Token", "")
        return hmac.compare_digest(token, provided)


class IsEditorOrAdmin(permissions.BasePermission):
    """Allow access only to users with editor or admin role."""

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.is_editor
