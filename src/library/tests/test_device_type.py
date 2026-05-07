"""Tests for the ``DeviceType`` model and its integration with ``VendorModel``."""

import pytest

from library.models import DeviceType, ProcessorConfig, Vendor, VendorModel


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
        assert vm.device_type == "water_meter", "charfield should be re-aligned to FK code on save"

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
        """Migration 0021 doesn't backfill — operator sets per-meter when needed."""
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


class TestEffectiveFieldMappings:
    """``effective_field_mappings`` resolves to:
    ``ProcessorConfig.field_mappings`` (override) when non-empty, else
    ``DeviceType.default_field_mappings``; with
    ``ProcessorConfig.extra_field_mappings`` always concatenated on top.

    ``primary_targets`` / ``secondary_targets`` partition by the per-entry
    ``primary`` flag (default false ⇒ secondary)."""

    @pytest.fixture
    def heat_with_defaults(self, heat_meter_type):
        heat_meter_type.default_field_mappings = [
            {"source": "energy_kwh", "target": "heat:total_energy", "transform": "to_float", "primary": True},
            {"source": "volume_m3", "target": "heat:total_volume", "transform": "to_float", "primary": True},
            {"source": "flow_temp", "target": "heat:flow_temperature", "transform": "to_float"},
        ]
        heat_meter_type.save(update_fields=["default_field_mappings"])
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

    def test_inherits_type_defaults_when_processor_config_missing(self, heat_with_defaults):
        vm = self._make_model(heat_with_defaults)
        assert vm.effective_field_mappings == heat_with_defaults.default_field_mappings

    def test_inherits_when_override_empty(self, heat_with_defaults):
        vm = self._make_model(heat_with_defaults)
        ProcessorConfig.objects.create(device_type=vm, field_mappings=[], extra_field_mappings=[])
        assert vm.effective_field_mappings == heat_with_defaults.default_field_mappings

    def test_override_replaces_default_entirely(self, heat_with_defaults):
        vm = self._make_model(heat_with_defaults, vendor_slug="overridden", vendor_name="Overridden")
        custom = [
            {"source": "kwh_total", "target": "heat:total_energy", "transform": "to_float", "primary": True},
        ]
        ProcessorConfig.objects.create(device_type=vm, field_mappings=custom)
        assert vm.effective_field_mappings == custom  # NOT merged with type defaults

    def test_extras_concatenated_on_top(self, heat_with_defaults):
        vm = self._make_model(heat_with_defaults, vendor_slug="extras", vendor_name="ExtrasVendor")
        extras = [
            {"source": "battery_v", "target": "heat:battery_v", "transform": "to_float"},
        ]
        ProcessorConfig.objects.create(
            device_type=vm,
            field_mappings=[],
            extra_field_mappings=extras,
        )
        effective = vm.effective_field_mappings
        # Type defaults first, then extras
        assert effective[: len(heat_with_defaults.default_field_mappings)] == heat_with_defaults.default_field_mappings
        assert effective[-1] == extras[0]

    def test_primary_secondary_partitioning(self, heat_with_defaults):
        vm = self._make_model(heat_with_defaults, vendor_slug="partitioned", vendor_name="Partitioned")
        ProcessorConfig.objects.create(
            device_type=vm,
            extra_field_mappings=[
                {"source": "rssi", "target": "heat:rssi", "transform": "identity"},
            ],
        )
        primary = vm.primary_targets
        secondary = vm.secondary_targets

        assert "heat:total_energy" in primary
        assert "heat:total_volume" in primary
        # Default flow_temp has no ``primary`` flag — secondary
        assert "heat:flow_temperature" in secondary
        # Extras default to secondary too
        assert "heat:rssi" in secondary
