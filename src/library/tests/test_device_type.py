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


class TestMetricValueBounds:
    """L1 value bounds — min/max hard caps + monotonic flag for cumulative
    counters. Migration 0031 seeds conservative defaults so Spark can
    replace its hardcoded METRIC_LIMITS / NON_NEGATIVE_METRICS tables."""

    def test_cumulative_counters_marked_monotonic(self):
        # Migration 0031 marks the canonical cumulative counters monotonic.
        assert Metric.objects.get(key="heat:total_energy").monotonic is True
        assert Metric.objects.get(key="water:total_volume").monotonic is True
        assert Metric.objects.get(key="gas:total_volume").monotonic is True
        assert Metric.objects.get(key="elec:total_energy").monotonic is True
        # Instantaneous quantities are not monotonic.
        assert Metric.objects.get(key="env:temperature").monotonic is False
        assert Metric.objects.get(key="elec:active_power").monotonic is False

    def test_seeded_bounds_for_temperature(self):
        # env:temperature seeded with −100..150 °C.
        t = Metric.objects.get(key="env:temperature")
        assert t.min_value == -100
        assert t.max_value == 150

    def test_seeded_cumulative_counters_have_non_negative_floor(self):
        # Anything monotonic should also have min_value=0 — a cumulative
        # counter going negative is physically impossible.
        for key in ["heat:total_energy", "water:total_volume", "gas:total_volume", "elec:total_energy"]:
            m = Metric.objects.get(key=key)
            assert m.min_value == 0, f"{key} cumulative counter must have min_value=0"

    def test_clean_rejects_min_greater_than_max(self):
        from django.core.exceptions import ValidationError

        m = Metric(key="x:bad", label="Bad", data_type="decimal", min_value=10, max_value=5)
        with pytest.raises(ValidationError):
            m.full_clean()

    def test_clean_allows_null_bounds(self):
        # Nulls = no opinion → no cross-field check should fire.
        m = Metric(key="x:freeform", label="Free", data_type="decimal")
        m.full_clean()  # should not raise

    def test_clean_allows_one_sided_cap(self):
        # Only min, no max — valid (consumer just skips the upper check).
        m = Metric(key="x:onesided", label="One-sided", data_type="decimal", min_value=0)
        m.full_clean()

    def test_auto_created_metrics_have_null_bounds(self, heat_meter_type):
        """ProcessorConfig.save() auto-creates Metric rows for unknown
        targets — they should start with no bounds opinion."""
        vendor = Vendor.objects.create(name="Auto", slug="auto")
        vm = VendorModel.objects.create(
            vendor=vendor,
            model_number="A-1",
            name="Auto A-1",
            device_type="heat_meter",
            device_type_fk=heat_meter_type,
            technology=VendorModel.Technology.WMBUS,
        )
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[{"source": "raw", "target": "heat:novel_metric"}],
        )
        m = Metric.objects.get(key="heat:novel_metric")
        assert m.min_value is None
        assert m.max_value is None
        assert m.monotonic is False


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
                {"source": "energy_kwh", "target": "heat:total_energy"},
                {"source": "temp_c", "target": "heat:flow_temperature"},
            ],
        )
        result = vm.effective_field_mappings
        by_source = {m["source"]: m for m in result}

        assert by_source["energy_kwh"]["target"] == "heat:total_energy"
        assert by_source["energy_kwh"]["label"] == "Total Energy"
        assert by_source["energy_kwh"]["unit"] == "kWh"
        assert by_source["energy_kwh"]["tier"] == "primary"

        assert by_source["temp_c"]["tier"] == "secondary"

    def test_metric_not_on_type_falls_back_to_diagnostic(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="diag", vendor_name="Diag")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "rssi_dbm", "target": "device:rssi"},
            ],
        )
        result = vm.effective_field_mappings
        assert result[0]["tier"] == "diagnostic"
        assert result[0]["unit"] == "dBm"

    def test_scale_passed_through_offset_omitted_when_zero(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="trans", vendor_name="Trans")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {
                    "source": "energy_wh",
                    "target": "heat:total_energy",
                    "scale": 0.001,
                },
            ],
        )
        entry = vm.effective_field_mappings[0]
        assert entry["scale"] == 0.001
        assert "offset" not in entry  # default 0 — omitted

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
                    "target": "env:temperature",
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
                {"source": "energy_kwh", "target": "heat:total_energy", "scale": 1, "offset": 0},
            ],
        )
        entry = vm.effective_field_mappings[0]
        # Default (scale=1, offset=0) → no-op, omitted from rendered output
        assert "scale" not in entry
        assert "offset" not in entry

    def test_unknown_target_auto_creates_l1_row(self, heat_with_profile):
        """Tolerant pattern: a model can reference a metric not in the
        catalogue, and saving the ProcessorConfig auto-creates the L1
        Metric row with sane defaults."""
        assert not Metric.objects.filter(key="temp:temperature_boiler").exists()

        vm = self._make_model(heat_with_profile, vendor_slug="boiler", vendor_name="Boiler")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "boiler_temp_c", "target": "temp:temperature_boiler"},
            ],
        )

        m = Metric.objects.get(key="temp:temperature_boiler")
        assert m.label == "Temperature Boiler"
        assert m.data_type == "decimal"
        # Unit defaults to empty — operator dials it in via admin afterwards
        assert m.unit == ""

    def test_multi_channel_via_separate_metric_keys(self, heat_meter_type):
        # 3-phase voltage modeled as three distinct L1 metrics (one per phase)
        heat_meter_type.metrics = [
            {"metric": "elec:voltage_l1", "tier": "primary"},
            {"metric": "elec:voltage_l2", "tier": "primary"},
            {"metric": "elec:voltage_l3", "tier": "primary"},
        ]
        heat_meter_type.save(update_fields=["metrics"])
        vm = self._make_model(heat_meter_type, vendor_slug="3ph", vendor_name="ThreePhase")
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[
                {"source": "voltage_l1", "target": "elec:voltage_l1"},
                {"source": "voltage_l2", "target": "elec:voltage_l2"},
                {"source": "voltage_l3", "target": "elec:voltage_l3"},
            ],
        )
        result = vm.effective_field_mappings
        assert len(result) == 3
        targets = {entry["target"] for entry in result}
        assert targets == {"elec:voltage_l1", "elec:voltage_l2", "elec:voltage_l3"}
        # All inherit the same tier from L2
        assert all(entry["tier"] == "primary" for entry in result)

    def test_decoder_type_autoderived_from_technology(self, water_meter_type):
        """``ProcessorConfig.save()`` auto-fills ``decoder_type`` based on
        VendorModel.technology so operators don't have to."""
        vendor = Vendor.objects.create(name="AutoDeriveVendor", slug="autoderive")
        # wmbus model
        wmbus_vm = VendorModel.objects.create(
            vendor=vendor,
            model_number="WB-1",
            name="WB-1",
            device_type="water_meter",
            device_type_fk=water_meter_type,
            technology=VendorModel.Technology.WMBUS,
        )
        wmbus_pc = ProcessorConfig.objects.create(device_type=wmbus_vm)
        wmbus_pc.refresh_from_db()
        assert wmbus_pc.decoder_type == "wmbus_field_map"

        # lorawan model without payload codec → lorawan_field_map
        lw_vm = VendorModel.objects.create(
            vendor=vendor,
            model_number="LW-1",
            name="LW-1",
            device_type="water_meter",
            device_type_fk=water_meter_type,
            technology=VendorModel.Technology.LORAWAN,
        )
        lw_pc = ProcessorConfig.objects.create(device_type=lw_vm)
        lw_pc.refresh_from_db()
        assert lw_pc.decoder_type == "lorawan_field_map"

    def test_declared_metrics_exposes_type_profile(self, heat_with_profile):
        vm = self._make_model(heat_with_profile, vendor_slug="decl", vendor_name="Decl")
        declared = vm.declared_metrics
        assert {"metric": "heat:total_energy", "tier": "primary"} in declared
        assert {"metric": "heat:flow_temperature", "tier": "secondary"} in declared
