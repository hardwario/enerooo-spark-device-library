"""End-to-end YAML export → import round trip (schema-v4)."""

import pytest
import yaml

from library.exporters import export_to_yaml
from library.importers import import_from_yaml
from library.models import Metric, ProcessorConfig, Vendor, VendorModel

pytestmark = pytest.mark.django_db


def test_export_manifest_carries_schema_v4_blocks(tmp_path, water_meter_type, heat_meter_type):
    """The exported manifest carries L1 Metric catalogue + L2 device_types."""
    output_dir = tmp_path / "devices"
    export_to_yaml(output_dir)

    manifest_path = tmp_path / "manifest.yaml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text())

    assert manifest["schema_version"] == 4
    assert "metrics" in manifest
    assert "device_types" in manifest

    # Seeded Metric catalogue present
    metric_keys = {m["key"] for m in manifest["metrics"]}
    assert "heat:total_energy" in metric_keys
    assert "water:total_volume" in metric_keys

    # Device types listed (no per-vendor models, so vendors block is empty,
    # but DeviceType seeds from migration 0021 are exported regardless)
    type_codes = {dt["code"] for dt in manifest["device_types"]}
    assert "water_meter" in type_codes
    assert "heat_meter" in type_codes


def test_export_device_type_carries_metrics_profile(tmp_path, heat_meter_type):
    """L2 profile is exported as ``metrics`` (not legacy ``default_field_mappings``)."""
    heat_meter_type.metrics = [
        {"metric": "heat:total_energy", "tier": "primary"},
        {"metric": "heat:flow_temperature", "tier": "secondary"},
    ]
    heat_meter_type.save(update_fields=["metrics"])

    export_to_yaml(tmp_path / "devices")
    manifest = yaml.safe_load((tmp_path / "manifest.yaml").read_text())

    heat_entry = next(dt for dt in manifest["device_types"] if dt["code"] == "heat_meter")
    assert "metrics" in heat_entry
    assert "default_field_mappings" not in heat_entry
    metrics_by_key = {m["metric"]: m for m in heat_entry["metrics"]}
    assert metrics_by_key["heat:total_energy"]["tier"] == "primary"
    assert metrics_by_key["heat:flow_temperature"]["tier"] == "secondary"


def test_round_trip_preserves_devicetype_metrics(tmp_path, heat_meter_type):
    """Exporting + re-importing ``DeviceType.metrics`` keeps the profile intact."""
    heat_meter_type.metrics = [
        {"metric": "heat:total_energy", "tier": "primary"},
        {"metric": "heat:total_volume", "tier": "primary"},
    ]
    heat_meter_type.save(update_fields=["metrics"])

    export_to_yaml(tmp_path / "devices")
    heat_meter_type.metrics = []
    heat_meter_type.save(update_fields=["metrics"])
    import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")

    heat_meter_type.refresh_from_db()
    assert len(heat_meter_type.metrics) == 2
    assert heat_meter_type.metrics[0]["metric"] == "heat:total_energy"
    assert heat_meter_type.metrics[0]["tier"] == "primary"


def test_round_trip_preserves_processor_field_mappings(tmp_path, water_meter_type):
    """L4 ``ProcessorConfig.field_mappings`` survives export → import."""
    vendor = Vendor.objects.create(name="Mappings Roundtrip", slug="mappings-roundtrip")
    vm = VendorModel.objects.create(
        vendor=vendor,
        model_number="MR-1",
        name="MR-1",
        device_type="water_meter",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )
    ProcessorConfig.objects.create(
        device_type=vm,
        decoder_type="js_codec",
        field_mappings=[
            {"source": "volume_m3", "metric": "water:total_volume"},
            {"source": "battery_mv", "metric": "device:battery", "transform": "identity"},
        ],
    )

    export_to_yaml(tmp_path / "devices")
    ProcessorConfig.objects.filter(device_type=vm).update(field_mappings=[])
    import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")

    proc = ProcessorConfig.objects.get(device_type=vm)
    assert len(proc.field_mappings) == 2
    keys = {m["metric"] for m in proc.field_mappings}
    assert keys == {"water:total_volume", "device:battery"}


def test_import_translates_legacy_default_field_mappings(tmp_path, heat_meter_type):
    """Schema-v3 manifests carried per-type ``default_field_mappings`` with
    ``target`` strings and per-entry ``primary`` flag. The v4 importer
    translates these to the L2 ``metrics`` profile shape."""
    manifest = {
        "schema_version": 3,
        "device_types": [
            {
                "code": "heat_meter",
                "label": "Heat Meter",
                "icon": "thermometer",
                "default_field_mappings": [
                    {"source": "energy_kwh", "target": "heat:total_energy", "primary": True},
                    {"source": "flow_temp", "target": "heat:flow_temperature"},
                ],
            },
        ],
        "vendors": [],
    }
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir(parents=True)
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))

    import_from_yaml(devices_dir, tmp_path / "manifest.yaml")

    heat_meter_type.refresh_from_db()
    by_key = {m["metric"]: m for m in heat_meter_type.metrics}
    assert by_key["heat:total_energy"]["tier"] == "primary"
    assert by_key["heat:flow_temperature"]["tier"] == "secondary"
    # Auto-created Metric rows for any unseeded targets
    assert Metric.objects.filter(key="heat:total_energy").exists()


def test_import_translates_legacy_processor_field_mappings(tmp_path, water_meter_type):
    """Schema-v3 had two slots and entries used ``target``/``unit``/``primary``.
    Schema-v4 importer collapses + renames + drops the obsolete fields."""
    vendor_yaml = {
        "models": [
            {
                "vendor_name": "Legacy",
                "model_number": "LG-1",
                "name": "LG-1",
                "device_type": "water_meter",
                "device_type_key": str(water_meter_type.key),
                "technology_config": {"technology": "wmbus", "manufacturer_code": "AAA"},
                "processor_config": {
                    "decoder_type": "js_codec",
                    "field_mappings": [
                        {"source": "volume_m3", "target": "water:total_volume", "unit": "m³", "primary": True},
                    ],
                    "extra_field_mappings": [
                        {"source": "battery_pct", "target": "device:battery", "unit": "ratio"},
                    ],
                },
            },
        ],
    }
    manifest = {
        "schema_version": 3,
        "device_types": [],
        "vendors": [{"name": "Legacy", "file": "legacy.yaml"}],
    }
    devices_dir = tmp_path / "devices"
    devices_dir.mkdir(parents=True)
    (tmp_path / "manifest.yaml").write_text(yaml.dump(manifest))
    (devices_dir / "legacy.yaml").write_text(yaml.dump(vendor_yaml))

    import_from_yaml(devices_dir, tmp_path / "manifest.yaml")

    vm = VendorModel.objects.get(vendor__slug="legacy", model_number="LG-1")
    proc = ProcessorConfig.objects.get(device_type=vm)
    by_source = {m["source"]: m for m in proc.field_mappings}
    assert by_source["volume_m3"]["metric"] == "water:total_volume"
    assert by_source["battery_pct"]["metric"] == "device:battery"
    # Per-entry unit + primary should be dropped (now lives in L1 / L2)
    assert "unit" not in by_source["volume_m3"]
    assert "primary" not in by_source["volume_m3"]
    assert "target" not in by_source["volume_m3"]


def test_import_resolves_device_type_fk_by_key(tmp_path, water_meter_type):
    """An import with a ``device_type_key`` matches the existing row."""
    manifest = {
        "schema_version": 4,
        "device_types": [],
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
    the FK via the ``device_type`` enum string."""
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
