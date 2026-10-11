"""Return the user to the page they came from after a create, edit or delete.

Links to mutation pages carry ``?next=<current page>`` (``{% url_with_next %}``
in ``library/templatetags/return_to.py``), forms post it back as a hidden
field (``partials/next_field.html``), and views redirect to it, falling back
to their usual target. An explicit parameter instead of the Referer header:
Referer can be stripped and points at the form itself after a re-render with
validation errors.
"""

from urllib.parse import parse_qs, urlencode, urlsplit

from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def get_next_url(request, exclude_prefix: str | None = None) -> str | None:
    """The request's ``next`` (POST, then GET) if it is a safe local URL, else None.

    ``exclude_prefix`` skips a ``next`` under that path, e.g. the detail page of
    an object that was just deleted, in favour of the ``next`` that page itself
    carried (where the user opened it from).
    """
    url = request.POST.get("next") or request.GET.get("next")
    while url:
        if not url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
            return None
        if not (exclude_prefix and url.startswith(exclude_prefix)):
            return url
        url = parse_qs(urlsplit(url).query).get("next", [None])[0]
    return None


def with_next(request, url: str) -> str:
    """``url`` carrying the request's safe ``next`` along, e.g. back to a confirm page."""
    next_url = get_next_url(request)
    return f"{url}?{urlencode({'next': next_url})}" if next_url else url


def redirect_back(request, default, exclude_prefix: str | None = None):
    """Redirect to the safe ``next`` URL, or to ``default`` (a URL, URL name or model)."""
    return redirect(get_next_url(request, exclude_prefix) or default)


class ReturnUrlMixin:
    """For class-based views: ``get_success_url`` returns ``self.get_return_url(<default>)``."""

    def get_return_url(self, default, exclude_prefix: str | None = None) -> str:
        return get_next_url(self.request, exclude_prefix) or str(default)


def next_url(request):
    """Context processor: the safe ``next`` URL as ``next_url``, for Cancel links and hidden fields."""
    return {"next_url": get_next_url(request)}
