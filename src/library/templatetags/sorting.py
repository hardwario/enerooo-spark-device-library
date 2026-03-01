"""Template tags for sortable table headers."""

from django import template
from django.utils.html import format_html, mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def sort_header(context, field, label, align="left"):
    """Render a sortable table header link.

    Usage: {% sort_header "name" "Name" %} or {% sort_header "device_count" "Total" "right" %}
    """
    request = context["request"]
    params = request.GET.copy()
    current_sort = params.get("sort", "")

    if current_sort == field:
        next_sort = f"-{field}"
        icon = '<i data-lucide="arrow-up" class="inline-block w-3.5 h-3.5 ml-1 text-blue-600"></i>'
    elif current_sort == f"-{field}":
        next_sort = field
        icon = '<i data-lucide="arrow-down" class="inline-block w-3.5 h-3.5 ml-1 text-blue-600"></i>'
    else:
        next_sort = field
        icon = '<i data-lucide="arrows-up-down" class="inline-block w-3 h-3 ml-1 text-gray-400"></i>'

    params["sort"] = next_sort
    params.pop("page", None)
    url = f"?{params.urlencode()}"

    return format_html(
        '<a href="{}" class="inline-flex items-center text-{} hover:text-blue-600">{}{}</a>',
        url,
        align,
        label,
        mark_safe(icon),
    )
