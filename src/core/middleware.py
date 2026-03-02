"""Core middleware."""

import time
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone


class AutoLogoutMiddleware:
    """Log out users who have been idle longer than AUTO_LOGOUT_IDLE_TIME."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        now = time.time()
        last_activity = request.session.get("last_activity")

        if last_activity and (now - last_activity) > settings.AUTO_LOGOUT_IDLE_TIME:
            request.session.flush()
            request.user = AnonymousUser()
            return redirect(f"{reverse(settings.LOGIN_URL)}?timeout=1")

        request.session["last_activity"] = now
        return self.get_response(request)


class TimezoneMiddleware:
    """Activate the user's preferred timezone for each request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            timezone.activate(ZoneInfo(request.user.timezone))
        else:
            timezone.deactivate()
        return self.get_response(request)
