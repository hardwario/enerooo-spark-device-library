"""Model detail history summary (PR #78 review fixes)."""

import pytest
from django.contrib.auth import get_user_model

from library.history import record_history, snapshot_device
from library.models import AlarmConfig, DeviceHistory, Vendor, VendorModel
from library.views import _changed_item_count

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def model(water_meter_type):
    vendor = Vendor.objects.create(name="Acme", slug="acme")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="WM1",
        name="Water Meter 1",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )


@pytest.fixture
def admin_client(client):
    client.force_login(User.objects.create_user(username="ad", password="x", role=User.Role.ADMIN))
    return client


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ([{"a": 1}] * 10, [{"a": 1}] * 9 + [{"a": 2}], 1),  # one of ten edited
        ([], [{"a": 1}, {"a": 2}], 2),  # two added
        ([{"a": 1}, {"a": 2}], [{"a": 1}], 1),  # one removed
        (None, [{"a": 1}], 1),  # list appeared
        ([{"a": 1}], [{"a": 1}], 0),
    ],
)
def test_changed_item_count(old, new, expected):
    assert _changed_item_count(old, new) == expected


def test_badge_counts_only_changed_alarm_mappings(admin_client, model):
    mappings = [{"alarm": f"water:a{i}", "match_type": "equals", "match": i} for i in range(10)]
    config = AlarmConfig.objects.create(device_type=model, mappings=mappings)
    record_history(model, DeviceHistory.Action.CREATED, None)

    before = snapshot_device(VendorModel.objects.get(pk=model.pk))
    config.mappings = mappings[:9] + [{**mappings[9], "match": 99}]
    config.save()
    record_history(VendorModel.objects.get(pk=model.pk), DeviceHistory.Action.UPDATED, None, before)

    body = admin_client.get(f"/models/{model.pk}/").content.decode()
    assert "1 item modified" in body
    assert "10 items modified" not in body


def test_models_list_ignores_xhr_header(admin_client):
    response = admin_client.get("/models/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert response.status_code == 200
