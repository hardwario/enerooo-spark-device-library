"""Core context processors."""

from importlib.metadata import version

from django.conf import settings


def app_version(request):
    """Add app version to template context."""
    return {
        "APP_VERSION": version("spark-device-library"),
        "COMPANY_NAME": getattr(settings, "COMPANY_NAME", "Spark Device Library"),
    }


def auto_logout(request):
    """Add auto-logout timeout settings to template context."""
    return {
        "AUTO_LOGOUT_IDLE_TIME": settings.AUTO_LOGOUT_IDLE_TIME,
        "AUTO_LOGOUT_WARNING_TIME": settings.AUTO_LOGOUT_WARNING_TIME,
    }
