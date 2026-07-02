"""TTN registration profile fields on LoRaWANConfig: serializer emit, YAML
round-trip, and the 0038 seed-migration mapping."""

import importlib

import pytest

from library.api.serializers import DeviceTechnologyConfigSerializer
from library.exporters import export_to_yaml
from library.importers import import_from_yaml
from library.models import LoRaWANConfig, Vendor, VendorModel

pytestmark = pytest.mark.django_db


def _lorawan_model(water_meter_type, **cfg):
    vendor = Vendor.objects.create(name="Milesight", slug="milesight")
    vm = VendorModel.objects.create(
        vendor=vendor,
        model_number="WS523",
        name="Milesight WS523",
        device_type="water_meter",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.LORAWAN,
    )
    LoRaWANConfig.objects.create(device_type=vm, **cfg)
    return vm


def test_serializer_emits_registration_fields(water_meter_type):
    vm = _lorawan_model(
        water_meter_type,
        device_class="C",
        lorawan_version="MAC_V1_0_3",
        lorawan_phy_version="PHY_V1_0_3_REV_A",
        frequency_plan_id="EU_863_870_TTN",
        join_eui_default="24E124C0002A0001",
    )
    data = DeviceTechnologyConfigSerializer(vm).data
    assert data["lorawan_version"] == "MAC_V1_0_3"
    assert data["lorawan_phy_version"] == "PHY_V1_0_3_REV_A"
    assert data["frequency_plan_id"] == "EU_863_870_TTN"
    assert data["join_eui_default"] == "24E124C0002A0001"
    # OTAA is the default -> supports_join omitted to keep the payload lean.
    assert "supports_join" not in data


def test_serializer_omits_blank_registration_fields(water_meter_type):
    vm = _lorawan_model(water_meter_type)  # all registration fields blank
    data = DeviceTechnologyConfigSerializer(vm).data
    for key in ("lorawan_version", "lorawan_phy_version", "frequency_plan_id", "join_eui_default"):
        assert key not in data


def test_round_trip_preserves_registration_fields(tmp_path, water_meter_type):
    vm = _lorawan_model(
        water_meter_type,
        lorawan_version="MAC_V1_0_2",
        lorawan_phy_version="PHY_V1_0_2_REV_A",
        frequency_plan_id="EU_863_870_TTN",
        join_eui_default="04B6480000000000",
    )
    export_to_yaml(tmp_path / "devices")
    LoRaWANConfig.objects.filter(device_type=vm).update(
        lorawan_version="", lorawan_phy_version="", frequency_plan_id="", join_eui_default=""
    )
    import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")

    cfg = LoRaWANConfig.objects.get(device_type=vm)
    assert cfg.lorawan_version == "MAC_V1_0_2"
    assert cfg.lorawan_phy_version == "PHY_V1_0_2_REV_A"
    assert cfg.frequency_plan_id == "EU_863_870_TTN"
    assert cfg.join_eui_default == "04B6480000000000"


def test_seed_migration_profile_mapping():
    mod = importlib.import_module(
        "library.migrations.0038_seed_lorawan_registration_profiles"
    )
    zenner = mod._profile_for("Zenner", "APZ V2 30 LRW")
    assert zenner["join_eui_default"] == "04B6480000000000"
    assert zenner["device_class"] == "A"

    ws = mod._profile_for("Milesight", "WS523")
    assert ws["device_class"] == "C"
    assert ws["join_eui_default"] == "24E124C0002A0001"

    wt = mod._profile_for("Milesight", "WT101")
    assert wt["device_class"] == "A"

    eastron = mod._profile_for("Eastron", "SDM630MCT-LR")
    assert eastron["lorawan_version"] == "MAC_V1_0_2"
    assert eastron["device_class"] == "C"
    assert "join_eui_default" not in eastron  # unverified -> left blank

    assert mod._profile_for("Axioma", "Qalcosonic W1 LRW") is None
