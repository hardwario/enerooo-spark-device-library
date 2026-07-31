"""Renaming a DeviceType code must propagate to the VendorModels that
mirror it, and published snapshots must carry the stable device_type_key."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from library.history import record_history, snapshot_device
from library.models import DeviceHistory, DeviceType, Vendor, VendorModel

User = get_user_model()


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user(
        username="rename-admin",
        password="x",
        is_staff=True,
        is_superuser=True,
        role="admin",
    )
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def inverter_setup(db):
    dtype = DeviceType.objects.create(code="solar_inventor", label="Solar inventor")
    vendor, _ = Vendor.objects.get_or_create(name="ENEROOO-T", slug="enerooo-t")
    vm = VendorModel.objects.create(
        vendor=vendor,
        model_number="ER10I-T",
        name="Test Inverter",
        device_type_fk=dtype,
        technology=VendorModel.Technology.MODBUS,
    )
    record_history(vm, DeviceHistory.Action.CREATED, user=None)
    return {"dtype": dtype, "vm": vm}


def test_code_rename_propagates_to_vendor_models(admin_client, inverter_setup):
    dtype, vm = inverter_setup["dtype"], inverter_setup["vm"]
    assert vm.device_type == "solar_inventor"  # save guard mirrored the FK
    history_before = DeviceHistory.objects.filter(device=vm).count()

    resp = admin_client.post(
        reverse("library:devicetype-edit", kwargs={"pk": dtype.pk}),
        {
            "code": "solar_inverter",
            "label": "Solar inverter",
            "description": "",
            "icon": "",
            "metrics": "[]",
        },
    )
    assert resp.status_code == 302

    vm.refresh_from_db()
    assert vm.device_type == "solar_inverter"
    # A new history version must exist, otherwise the publish flow keeps
    # pinning the pre-rename snapshot and consumers never see the new code.
    assert DeviceHistory.objects.filter(device=vm).count() == history_before + 1
    latest = DeviceHistory.objects.filter(device=vm).order_by("-version").first()
    assert latest.snapshot["device_type"] == "solar_inverter"


def test_save_without_code_change_does_not_touch_models(admin_client, inverter_setup):
    dtype, vm = inverter_setup["dtype"], inverter_setup["vm"]
    history_before = DeviceHistory.objects.filter(device=vm).count()

    resp = admin_client.post(
        reverse("library:devicetype-edit", kwargs={"pk": dtype.pk}),
        {
            "code": "solar_inventor",
            "label": "Relabel only",
            "description": "",
            "icon": "",
            "metrics": "[]",
        },
    )
    assert resp.status_code == 302
    assert DeviceHistory.objects.filter(device=vm).count() == history_before


def test_snapshot_carries_device_type_key(inverter_setup):
    snap = snapshot_device(inverter_setup["vm"])
    assert snap["device_type_key"] == str(inverter_setup["dtype"].key)

    from library.exporters import snapshot_to_schema

    schema = snapshot_to_schema(snap)
    assert schema["device_type_key"] == str(inverter_setup["dtype"].key)
