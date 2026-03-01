"""Core middleware."""

from zoneinfo import ZoneInfo

from django.utils import timezone


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
