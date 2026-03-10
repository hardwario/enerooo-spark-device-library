"""Template filters for JSON formatting."""

import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def pretty_json(value):
    """Render a dict/list as syntax-highlighted, indented JSON."""
    if not value:
        return ""
    try:
        raw = json.dumps(value, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)

    # Simple syntax highlighting
    import re

    escaped = raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Highlight strings (keys and values)
    escaped = re.sub(
        r'("(?:[^"\\]|\\.)*")\s*:',
        r'<span class="text-purple-700">\1</span>:',
        escaped,
    )
    escaped = re.sub(
        r':\s*("(?:[^"\\]|\\.)*")',
        lambda m: f': <span class="text-green-700">{m.group(1)}</span>',
        escaped,
    )
    # Highlight numbers
    escaped = re.sub(
        r":\s*(\d+\.?\d*)",
        lambda m: f': <span class="text-blue-700">{m.group(1)}</span>',
        escaped,
    )
    # Highlight booleans and null
    escaped = re.sub(
        r"\b(true|false|null)\b",
        r'<span class="text-amber-700">\1</span>',
        escaped,
    )

    return mark_safe(escaped)
