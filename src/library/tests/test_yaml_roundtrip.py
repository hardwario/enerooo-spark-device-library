"""End-to-end YAML export → import round trip."""

import pytest
import yaml

from library.exporters import export_to_yaml
from library.importers import import_from_yaml
from library.models import ProcessorConfig, Vendor, VendorModel

pytestmark = pytest.mark.django_db


def test_export_writes_device_types_section(tmp_path, water_meter_type, heat_meter_type):
    """The manifest produced by ``export_to_yaml`` carries the
    ``device_types`` section with every populated row."""
    output_dir = tmp_path / "devices"
    export_to_yaml(output_dir)

    manifest_path = tmp_path / "manifest.yaml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text())

    assert manifest["schema_version"] == 3
    assert "device_types" in manifest
    codes = {dt["code"] for dt in manifest["device_types"]}
    assert "water_meter" in codes
    assert "heat_meter" in codes


def test_export_vendor_yaml_includes_device_type_key(tmp_path, water_meter_type):
    vendor = Vendor.objects.create(name="Round Trip Water", slug="round-trip-water")
    VendorModel.objects.create(
        vendor=vendor,
        model_number="RT-1",
        name="RT-1",
        device_type="water_meter",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )

    export_to_yaml(tmp_path / "devices")

    vendor_yaml = yaml.safe_load((tmp_path / "devices" / "round-trip-water.yaml").read_text())
    model_entry = vendor_yaml["models"][0]
    assert model_entry["device_type"] == "water_meter"
    assert model_entry["device_type_key"] == str(water_meter_type.key)


def test_round_trip_preserves_device_type_default_field_mappings(tmp_path, heat_meter_type):
    """Exporting + re-importing ``DeviceType.default_field_mappings`` keeps
    the per-type mapping list intact."""
    heat_meter_type.default_field_mappings = [
        {"source": "energy_kwh", "target": "heat:total_energy", "transform": "to_float", "primary": True},
        {"source": "volume_m3", "target": "heat:total_volume", "transform": "to_float", "primary": True},
    ]
    heat_meter_type.save(update_fields=["default_field_mappings"])

    export_to_yaml(tmp_path / "devices")

    # Tamper, re-import, verify restoration
    heat_meter_type.default_field_mappings = []
    heat_meter_type.save(update_fields=["default_field_mappings"])
    import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")

    heat_meter_type.refresh_from_db()
    assert len(heat_meter_type.default_field_mappings) == 2
    assert heat_meter_type.default_field_mappings[0]["target"] == "heat:total_energy"
    assert heat_meter_type.default_field_mappings[0]["primary"] is True


def test_round_trip_preserves_processor_extra_field_mappings(tmp_path, water_meter_type):
    """Per-model ``extra_field_mappings`` survives the export → import cycle."""
    vendor = Vendor.objects.create(name="Extras Roundtrip", slug="extras-roundtrip")
    vm = VendorModel.objects.create(
        vendor=vendor,
        model_number="ER-1",
        name="ER-1",
        device_type="water_meter",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )
    ProcessorConfig.objects.create(
        device_type=vm,
        decoder_type="js_codec",
        extra_field_mappings=[
            {"source": "battery_mv", "target": "water:battery_mv", "transform": "to_int"},
        ],
    )

    export_to_yaml(tmp_path / "devices")
    # Wipe to confirm the value comes back from YAML
    ProcessorConfig.objects.filter(device_type=vm).update(extra_field_mappings=[])
    import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")

    proc = ProcessorConfig.objects.get(device_type=vm)
    assert len(proc.extra_field_mappings) == 1
    assert proc.extra_field_mappings[0]["target"] == "water:battery_mv"


def test_import_resolves_device_type_fk_by_key(tmp_path, water_meter_type):
    """An import with a ``device_type_key`` matches the existing row."""
    manifest = {
        "schema_version": 3,
        "device_types": [],  # rely on the fixture-provided row
        "vendors": [{"name": "Imported", "file": "imported.yaml"}],
    }
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir(parents=True)
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (devices_dir / "imported.yaml").write_text(
        yaml.dump({
            "models": [
                {
                    "vendor_name": "Imported",
                    "model_number": "IM-1",
                    "name": "IM-1",
                    "device_type": "water_meter",
                    "device_type_key": str(water_meter_type.key),
                    "technology_config": {"technology": "wmbus", "manufacturer_code": "AAA"},
                },
            ],
        }),
    )

    import_from_yaml(devices_dir, tmp_path / "manifest.yaml")

    vm = VendorModel.objects.get(vendor__slug="imported", model_number="IM-1")
    assert vm.device_type_fk_id == water_meter_type.id
    assert vm.device_type == "water_meter"


def test_import_falls_back_to_code_when_key_missing(tmp_path, gas_meter_type):
    """Importing a manifest without ``device_type_key`` should still resolve
    the FK via the ``device_type`` enum string — that's the schema-v2 path."""
    manifest = {
        "schema_version": 2,
        "vendors": [{"name": "Fallback", "file": "fallback.yaml"}],
    }
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir(parents=True)
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (devices_dir / "fallback.yaml").write_text(
        yaml.dump({
            "models": [
                {
                    "vendor_name": "Fallback",
                    "model_number": "FB-1",
                    "name": "FB-1",
                    "device_type": "gas_meter",
                    "technology_config": {"technology": "wmbus", "manufacturer_code": "BBB"},
                },
            ],
        }),
    )

    import_from_yaml(devices_dir, tmp_path / "manifest.yaml")

    vm = VendorModel.objects.get(vendor__slug="fallback", model_number="FB-1")
    assert vm.device_type_fk_id == gas_meter_type.id
