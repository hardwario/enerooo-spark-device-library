"""Docker development settings."""

from .base import *  # noqa: F401, F403
from .base import env

# GENERAL
# ------------------------------------------------------------------------------
DEBUG = True
SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="docker-dev-secret-key",
)
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]", "web"]

# EMAIL
# ------------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
