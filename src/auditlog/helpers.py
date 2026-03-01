"""Audit log helper functions."""

import logging

from .models import AuditLog

logger = logging.getLogger(__name__)

# Map model class names to audit log categories
_CATEGORY_MAP = {
    "DeviceType": AuditLog.Category.DEVICE,
    "Vendor": AuditLog.Category.VENDOR,
    "LibraryVersion": AuditLog.Category.VERSION,
    "APIKey": AuditLog.Category.APIKEY,
    "User": AuditLog.Category.USER,
    "Invitation": AuditLog.Category.USER,
    "RegisterDefinition": AuditLog.Category.DEVICE,
}


def _get_client_ip(request):
    """Extract client IP from request."""
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def log_action(request, action, target, category="", details=""):
    """Record a user action in the audit log.

    Args:
        request: Django HTTP request (provides user and IP).
        action: Action string, e.g. "created", "deleted".
        target: The model instance being acted on.
        category: Optional override; auto-detected from target type if empty.
        details: Extra context — string or dict.

    Returns:
        AuditLog instance or None on error.
    """
    try:
        if not category:
            category = _CATEGORY_MAP.get(type(target).__name__, "")

        if isinstance(details, str) and details:
            details = {"message": details}
        elif not details:
            details = {}

        target_id = None
        if hasattr(target, "pk"):
            target_id = target.pk

        return AuditLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            category=category,
            action=action,
            target_type=type(target).__name__,
            target_id=target_id,
            target_label=str(target)[:255],
            details=details,
            ip_address=_get_client_ip(request),
        )
    except Exception:
        logger.exception("Failed to write audit log")
        return None
