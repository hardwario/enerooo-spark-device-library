"""Core context processors."""

from django.conf import settings


def app_version(request):
    """Add app version to template context."""
    return {
        "APP_VERSION": "0.1.0",
        "COMPANY_NAME": getattr(settings, "COMPANY_NAME", "Spark Device Library"),
    }
