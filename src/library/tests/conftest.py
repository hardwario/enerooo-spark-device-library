"""Shared pytest fixtures for the library tests."""

import pytest

from library.models import DeviceType

# Migration 0021 seeds the standard device types, so fixtures use
# ``get_or_create`` to stay idempotent against that seeding.


@pytest.fixture
def water_meter_type(db):
    obj, _ = DeviceType.objects.get_or_create(
        code="water_meter",
        defaults={"label": "Water Meter", "icon": "droplet"},
    )
    return obj


@pytest.fixture
def heat_meter_type(db):
    obj, _ = DeviceType.objects.get_or_create(
        code="heat_meter",
        defaults={"label": "Heat Meter", "icon": "thermometer"},
    )
    return obj


@pytest.fixture
def gas_meter_type(db):
    obj, _ = DeviceType.objects.get_or_create(
        code="gas_meter",
        defaults={"label": "Gas Meter", "icon": "flame"},
    )
    return obj
