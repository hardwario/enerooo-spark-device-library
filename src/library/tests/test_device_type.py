"""Tests for the schema-v4 mapping architecture (L1 Metric / L2 DeviceType
profile / L4 ProcessorConfig.field_mappings)."""

import pytest

from library.models import Metric, ProcessorConfig, Vendor, VendorModel

pytestmark = pytest.mark.django_db


class TestVendorModelDeviceTypeFK:
    """``VendorModel.device_type_fk`` is the canonical pointer; the legacy
    ``device_type`` charfield mirrors ``device_type_fk.code`` on save so
    older sync clients keep seeing a consistent enum value."""

    def test_save_syncs_charfield_from_fk(self, water_meter_type):
        vendor = Vendor.objects.create(name="Acme", slug="acme")
        vm = VendorModel.objects.create(
            vendor=vendor,
            model_number="W-1",
            name="Acme W-1",
            device_type="gas_meter",  # intentional mismatch
            device_type_fk=water_meter_type,
            technology=VendorModel.Technology.WMBUS,
        )
        vm.refresh_from_db()
        assert vm.device_type == "water_meter"

    def test_protect_blocks_delete_of_referenced_type(self, water_meter_type):
        from django.db.models import ProtectedError

        vendor = Vendor.objects.create(name="Gamma", slug="gamma")
        VendorModel.objects.create(
            vendor=vendor,
            model_number="W-9",
            name="Gamma W-9",
            device_type="water_meter",
            device_type_fk=water_meter_type,
            technology=VendorModel.Technology.WMBUS,
        )
        with pytest.raises(ProtectedError):
            water_meter_type.delete()

    def test_offline_window_starts_null(self, water_meter_type):
        vendor = Vendor.objects.create(name="Delta", slug="delta")
        vm = VendorModel.objects.create(
            vendor=vendor,
            model_number="W-2",
            name="Delta W-2",
            device_type="water_meter",
            device_type_fk=water_meter_type,
            technology=VendorModel.Technology.WMBUS,
        )
        assert vm.offline_window_seconds is None


class TestMetricCatalogue:
    """L1 — Global Metric catalogue: namespaced keys, canonical unit/label."""

    def test_seeded_metrics_present(self):
        # Migration 0022 seeds the standard metric catalogue.
        assert Metric.objects.filter(key="heat:total_energy").exists()
        assert Metric.objects.filter(key="water:total_volume").exists()
        assert Metric.objects.filter(key="device:battery").exists()
        assert Metric.objects.filter(key="device:rssi").exists()
        assert Metric.objects.filter(key="device:status").exists()

    def test_namespace_and_name_split(self):
        m = Metric.objects.get(key="heat:total_energy")
        assert m.namespace == "heat"
        assert m.name == "total_energy"

    def test_unit_for_seeded_metrics(self):
        assert Metric.objects.get(key="heat:total_energy").unit == "kWh"
        assert Metric.objects.get(key="water:total_volume").unit == "m³"
        assert Metric.objects.get(key="device:rssi").unit == "dBm"


class TestDeviceTypeProfile:
    """L2 — DeviceType.metrics declares which canonical metrics this type
    tracks and at which tier (primary / secondary / diagnostic)."""

    @pytest.fixture
    def heat_with_profile(self, heat_meter_type):
        heat_meter_type.metrics = [
            {"metric": "heat:total_energy", "tier": "primary"},
            {"metric": "heat:total_volume", "tier": "primary"},
            {"metric": "heat:flow_temperature", "tier": "secondary"},
            {"metric": "device:battery", "tier": "diagnostic"},
        ]
        heat_meter_type.save(update_fields=["metrics"])
        return heat_meter_type

    def test_tier_choices_enum(self, heat_meter_type):
        from library.models import DeviceType
        assert DeviceType.Tier.PRIMARY == "primary"
        assert DeviceType.Tier.SECONDARY == "secondary"
        assert DeviceType.Tier.DIAGNOSTIC == "diagnostic"


class TestEffectiveFieldMappings:
    """L4 — ``VendorModel.effective_field_mappings`` annotates each entry
    with label/unit (from L1 Metric) and tier (from L2 DeviceType.metrics).
    Entries whose metric isn't declared on the type fall back to
    tier=diagnostic."""

    @pytest.fixture
    def heat_with_profile(self, heat_meter_type):
        heat_meter_type.metrics = [
            {"metric": "heat:total_energy", "tier": "primary"},
            {"metric": "heat:total_volume", "tier": "primary"},
            {"metric": "heat:flow_temperature", "tier": "secondary"},
        ]
        heat_meter_type.save(update_fields=["metrics"])
        return heat_meter_type

    def _make_model(self, dt, **kwargs):
        vendor = Vendor.objects.create(
            name=kwargs.pop("vendor_name", "TestVendor"),
            slug=kwargs.pop("vendor_slug", "testvendor"),
        )
        return VendorModel.objects.create(
            vendor=vendor,
            model_number=kwargs.pop("model_number", "M-1"),
            name=kwargs.pop("name", "M-1"),
            device_type=dt.code,
            device_type_fk=dt,
            technology=VendorModel.Technology.LORAWAN,
            **kwargs,
        )

    def test_empty_field_mappings_yields_empty_effective(self, heat_with_profile):
        vm = self._make_model(heat_with_profile)
        assert vm.effective_field_mappings == []

    def test_entries_annotated_with_label_unit_tier(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="annotated", vendor_name="Annotated")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "energy_kwh", "metric": "heat:total_energy"},
                {"source": "temp_c", "metric": "heat:flow_temperature"},
            ],
        )
        result = vm.effective_field_mappings
        by_source = {m["source"]: m for m in result}

        assert by_source["energy_kwh"]["metric"] == "heat:total_energy"
        assert by_source["energy_kwh"]["label"] == "Total Energy"
        assert by_source["energy_kwh"]["unit"] == "kWh"
        assert by_source["energy_kwh"]["tier"] == "primary"

        assert by_source["temp_c"]["tier"] == "secondary"

    def test_metric_not_on_type_falls_back_to_diagnostic(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="diag", vendor_name="Diag")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "rssi_dbm", "metric": "device:rssi"},
            ],
        )
        result = vm.effective_field_mappings
        assert result[0]["tier"] == "diagnostic"
        assert result[0]["unit"] == "dBm"

    def test_scale_offset_and_tags_passed_through(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="trans", vendor_name="Trans")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {
                    "source": "energy_wh",
                    "metric": "heat:total_energy",
                    "scale": 0.001,
                    "tags": {"channel": "1"},
                },
            ],
        )
        entry = vm.effective_field_mappings[0]
        assert entry["scale"] == 0.001
        assert "offset" not in entry  # default 0 — omitted
        assert entry["tags"] == {"channel": "1"}

    def test_scale_and_offset_for_temperature_conversion(self, heat_meter_type):
        # °F → °C: value * (5/9) - 17.78
        heat_meter_type.metrics = [{"metric": "env:temperature", "tier": "secondary"}]
        heat_meter_type.save(update_fields=["metrics"])
        vm = self._make_model(heat_meter_type, vendor_slug="ftoc", vendor_name="FtoC")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {
                    "source": "temp_f",
                    "metric": "env:temperature",
                    "scale": 0.5556,
                    "offset": -17.78,
                },
            ],
        )
        entry = vm.effective_field_mappings[0]
        assert entry["scale"] == 0.5556
        assert entry["offset"] == -17.78

    def test_default_scale_and_offset_omitted_from_output(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="def", vendor_name="Def")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "energy_kwh", "metric": "heat:total_energy", "scale": 1, "offset": 0},
            ],
        )
        entry = vm.effective_field_mappings[0]
        # Default (scale=1, offset=0) → no-op, omitted from rendered output
        assert "scale" not in entry
        assert "offset" not in entry

    def test_unknown_metric_auto_creates_l1_row(self, heat_with_profile):
        """Tolerant pattern: a model can reference a metric not in the
        catalogue, and saving the ProcessorConfig auto-creates the L1
        Metric row with sane defaults."""
        assert not Metric.objects.filter(key="temp:temperature_boiler").exists()

        vm = self._make_model(heat_with_profile, vendor_slug="boiler", vendor_name="Boiler")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "boiler_temp_c", "metric": "temp:temperature_boiler"},
            ],
        )

        m = Metric.objects.get(key="temp:temperature_boiler")
        assert m.label == "Temperature Boiler"
        assert m.data_type == "decimal"
        # Unit defaults to empty — operator dials it in via admin afterwards
        assert m.unit == ""

    def test_multi_channel_via_tags(self, heat_meter_type):
        # 3-phase voltage modeled via tags, one entry per phase
        heat_meter_type.metrics = [{"metric": "elec:voltage", "tier": "primary"}]
        heat_meter_type.save(update_fields=["metrics"])
        vm = self._make_model(heat_meter_type, vendor_slug="3ph", vendor_name="ThreePhase")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "voltage_l1", "metric": "elec:voltage", "tags": {"phase": "L1"}},
                {"source": "voltage_l2", "metric": "elec:voltage", "tags": {"phase": "L2"}},
                {"source": "voltage_l3", "metric": "elec:voltage", "tags": {"phase": "L3"}},
            ],
        )
        result = vm.effective_field_mappings
        assert len(result) == 3
        # All resolve to the same metric but distinguish via tags
        phases = {entry["tags"]["phase"] for entry in result}
        assert phases == {"L1", "L2", "L3"}
        # All inherit the same tier from L2
        assert all(entry["tier"] == "primary" for entry in result)

    def test_declared_metrics_exposes_type_profile(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="decl", vendor_name="Decl")
        declared = vm.declared_metrics
        assert {"metric": "heat:total_energy", "tier": "primary"} in declared
        assert {"metric": "heat:flow_temperature", "tier": "secondary"} in declared
