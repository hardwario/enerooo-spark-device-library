"""``{% url_with_next %}``: a URL that returns to the current page afterwards (see core.return_url)."""

from urllib.parse import urlencode

from django import template
from django.urls import reverse

register = template.Library()


@register.simple_tag(takes_context=True)
def url_with_next(context, view_name, *args):
    """``{% url_with_next 'library:metric-edit' m.pk %}`` -> ``/metrics/<pk>/edit/?next=<current page>``."""
    url = reverse(view_name, args=args)
    request = context.get("request")
    if request is None:
        return url
    return f"{url}?{urlencode({'next': request.get_full_path()})}"
