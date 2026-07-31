"""Library filters for list views."""

import django_filters
from django.db import models

from .models import DeviceType, VendorModel


def device_type_choices():
    """(code, label) pairs from the DeviceType catalogue — the catalogue,
    not a hardcoded enum, defines which types exist."""
    return list(DeviceType.objects.values_list("code", "label"))


class VendorModelFilter(django_filters.FilterSet):
    vendor = django_filters.CharFilter(field_name="vendor__slug", lookup_expr="exact")
    technology = django_filters.ChoiceFilter(choices=VendorModel.Technology.choices)
    device_type = django_filters.ChoiceFilter(choices=device_type_choices)
    search = django_filters.CharFilter(method="filter_search")

    class Meta:
        model = VendorModel
        fields = ["vendor", "technology", "device_type"]

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            models.Q(name__icontains=value)
            | models.Q(model_number__icontains=value)
            | models.Q(vendor__name__icontains=value)
        )
