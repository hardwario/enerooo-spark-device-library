"""Template tags for device type display."""

from django import template
from django.utils.html import format_html

register = template.Library()

DEVICE_TYPE_COLORS = {
    "power_meter": "bg-blue-100 text-blue-700",
    "gateway": "bg-gray-100 text-gray-700",
    "environment_sensor": "bg-green-100 text-green-700",
    "water_meter": "bg-cyan-100 text-cyan-700",
    "heat_meter": "bg-orange-100 text-orange-700",
    "heat_cost_allocator": "bg-red-100 text-red-700",
    "gas_meter": "bg-yellow-100 text-yellow-700",
    "thermostat_head": "bg-purple-100 text-purple-700",
    "smart_plug": "bg-indigo-100 text-indigo-700",
}


@register.simple_tag
def device_type_badge(device_type, label=None):
    """Render a device type as a colored badge.

    Usage:
        {% device_type_badge "water_meter" %}
        {% device_type_badge "water_meter" "Water Meter" %}
        {% device_type_badge device.device_type device.get_device_type_display %}
    """
    if not label:
        label = device_type.replace("_", " ").title() if device_type else ""
    colors = DEVICE_TYPE_COLORS.get(device_type, "bg-gray-100 text-gray-700")
    return format_html(
        '<span class="inline-flex px-2 py-0.5 text-xs font-semibold rounded-full {}">{}</span>',
        colors,
        label,
    )
