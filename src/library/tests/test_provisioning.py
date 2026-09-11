"""``VendorModel.product_code`` + ``provisioning`` (L1 of the Provisioning plan)."""

import time

import pytest
import yaml
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework.test import APIClient

from library.exporters import export_to_yaml, snapshot_to_schema
from library.history import record_history, snapshot_device
from library.importers import import_from_yaml
from library.models import DeviceHistory, LibraryVersion, LibraryVersionDevice, Vendor, VendorModel
from library.provisioning import TEMPLATES, validate_provisioning

pytestmark = pytest.mark.django_db
User = get_user_model()

WMBUS_SCHEMA = TEMPLATES["wmbus"]


@pytest.fixture
def model(water_meter_type):
    vendor = Vendor.objects.create(name="Zenner", slug="zenner")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="APZ V2",
        name="APZ V2 30°",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )


@pytest.fixture
def editor_client(db):
    user = User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR)
    client = APIClient()
    client.force_login(user)
    return client


# --- product_code -----------------------------------------------------------


def test_product_code_regex(model):
    model.product_code = "er10v"
    with pytest.raises(ValidationError):
        model.full_clean()
    model.product_code = "ER10V"
    model.full_clean()


def test_product_code_empty_string_becomes_null(model):
    model.product_code = ""
    model.full_clean()
    assert model.product_code is None


def test_product_code_unique(model, water_meter_type):
    model.product_code = "ER10V"
    model.save()
    other = VendorModel(
        vendor=model.vendor, model_number="X", name="X", device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS, product_code="ER10V",
    )
    with pytest.raises(IntegrityError):
        other.save()


def test_many_models_without_code_allowed(model, water_meter_type):
    VendorModel.objects.create(
        vendor=model.vendor, model_number="Y", name="Y", device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )
    assert VendorModel.objects.filter(product_code__isnull=True).count() == 2


# --- provisioning schema ----------------------------------------------------


@pytest.mark.parametrize("technology", sorted(TEMPLATES))
def test_templates_are_valid(technology):
    validate_provisioning(TEMPLATES[technology])


def test_empty_schema_is_valid():
    validate_provisioning({})
    validate_provisioning(None)


def _field(**overrides):
    base = {"key": "dev_eui", "label": "DevEUI", "type": "hex", "length": 16, "required": True}
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "schema",
    [
        "not a dict",
        {"input_data": "nope"},
        {"input_data": [_field()], "pairing_key": "missing"},
        {"input_data": [_field()]},  # pairing_key required when fields exist
        {"input_data": [], "pairing_key": "dev_eui"},
        {"input_data": [_field(key="DevEUI")], "pairing_key": "DevEUI"},
        {"input_data": [_field(), _field()], "pairing_key": "dev_eui"},  # duplicate key
        {"input_data": [_field(label="")], "pairing_key": "dev_eui"},
        {"input_data": [_field(label={"en": "DevEUI"})], "pairing_key": "dev_eui"},
        {"input_data": [_field(type="uuid")], "pairing_key": "dev_eui"},
        {"input_data": [_field(length=None)], "pairing_key": "dev_eui"},
        {"input_data": [_field(length="16")], "pairing_key": "dev_eui"},
        {"input_data": [_field(type="int", length=None, min=10, max=1)], "pairing_key": "dev_eui"},
        {"input_data": [_field(type="string", length=None, pattern="[")], "pairing_key": "dev_eui"},
        {"input_data": [_field(required="yes")], "pairing_key": "dev_eui"},
        {"input_data": [_field()], "pairing_key": "dev_eui", "extra": 1},
    ],
)
def test_invalid_schemas_rejected(schema):
    with pytest.raises(ValidationError):
        validate_provisioning(schema)


def test_model_clean_runs_schema_validation(model):
    model.provisioning = {"input_data": [_field()], "pairing_key": "nope"}
    with pytest.raises(ValidationError) as exc:
        model.full_clean()
    assert "provisioning" in exc.value.message_dict


# --- snapshot / content / YAML ---------------------------------------------


def test_snapshot_and_content_carry_fields(model):
    model.product_code = "ER10V"
    model.provisioning = WMBUS_SCHEMA
    model.save()
    snap = snapshot_device(model)
    assert snap["product_code"] == "ER10V"
    assert snap["provisioning"] == WMBUS_SCHEMA
    schema = snapshot_to_schema(snap)
    assert schema["product_code"] == "ER10V"
    assert schema["provisioning"]["pairing_key"] == "wmbus_id"


def test_content_null_code_and_empty_schema_for_plain_model(model):
    schema = snapshot_to_schema(snapshot_device(model))
    assert schema["product_code"] is None
    assert schema["provisioning"] == {}


def test_published_content_endpoint_exposes_fields(model, settings):
    model.product_code = "ER10V"
    model.provisioning = WMBUS_SCHEMA
    model.save()
    record_history(model, DeviceHistory.Action.CREATED, None)
    version = LibraryVersion.objects.create(version=1, is_current=True)
    LibraryVersionDevice.objects.create(
        library_version=version, device_type=model, device_version=1,
        device_label=str(model), change_type=LibraryVersionDevice.ChangeType.ADDED,
    )
    settings.SERVICE_TOKEN = "t0k3n"
    client = APIClient()
    client.credentials(HTTP_X_SERVICE_TOKEN="t0k3n", HTTP_X_TIMESTAMP=str(int(time.time())))

    body = client.get("/api/v1/library/content/1/").json()
    published = body["vendors"][0]["models"][0]
    assert published["product_code"] == "ER10V"
    assert published["provisioning"]["input_data"][0]["key"] == "wmbus_id"


def test_devices_api_exposes_fields(model):
    model.product_code = "ER10V"
    model.provisioning = WMBUS_SCHEMA
    model.save()
    user = User.objects.create_user(username="s", password="x", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=user)

    listing = client.get("/api/v1/devices/").json()
    items = listing["results"] if isinstance(listing, dict) else listing
    assert items[0]["product_code"] == "ER10V"
    detail = client.get(f"/api/v1/devices/{model.pk}/").json()
    assert detail["provisioning"] == WMBUS_SCHEMA


def test_yaml_roundtrip(tmp_path, model):
    model.product_code = "ER10V"
    model.provisioning = WMBUS_SCHEMA
    model.save()
    export_to_yaml(tmp_path / "devices")
    files = list((tmp_path / "devices").glob("*.yaml"))
    exported = yaml.safe_load(files[0].read_text())["models"][0]
    assert exported["product_code"] == "ER10V"
    assert exported["provisioning"] == WMBUS_SCHEMA

    VendorModel.objects.all().delete()
    import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")
    restored = VendorModel.objects.get(model_number="APZ V2")
    assert restored.product_code == "ER10V"
    assert restored.provisioning == WMBUS_SCHEMA


def test_yaml_export_omits_empty_fields(tmp_path, model):
    export_to_yaml(tmp_path / "devices")
    exported = yaml.safe_load(next((tmp_path / "devices").glob("*.yaml")).read_text())["models"][0]
    assert "product_code" not in exported
    assert "provisioning" not in exported


# --- UI ---------------------------------------------------------------------


def test_provisioning_edit_view_saves_and_records_history(editor_client, model):
    import json

    url = f"/models/{model.pk}/provisioning/edit/"
    assert editor_client.get(url).status_code == 200
    response = editor_client.post(url, {"provisioning": json.dumps(WMBUS_SCHEMA)})
    assert response.status_code == 302
    model.refresh_from_db()
    assert model.provisioning == WMBUS_SCHEMA
    assert model.history.filter(action=DeviceHistory.Action.UPDATED).exists()


def test_provisioning_edit_view_rejects_invalid(editor_client, model):
    import json

    bad = {"input_data": [_field()], "pairing_key": "nope"}
    response = editor_client.post(f"/models/{model.pk}/provisioning/edit/", {"provisioning": json.dumps(bad)})
    assert response.status_code == 200
    assert b"pairing_key" in response.content
    model.refresh_from_db()
    assert model.provisioning == {}


def test_model_form_uppercases_product_code(editor_client, model):
    response = editor_client.post(
        f"/models/{model.pk}/edit/",
        {
            "vendor": model.vendor.pk,
            "model_number": model.model_number,
            "name": model.name,
            "device_type_fk": model.device_type_fk.pk,
            "technology": model.technology,
            "description": "",
            "product_code": "er10v",
        },
    )
    assert response.status_code == 302
    model.refresh_from_db()
    assert model.product_code == "ER10V"
