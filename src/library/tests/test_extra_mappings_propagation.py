"""Extra mappings must survive the publish -> content-sync path.

Regression: version snapshots dropped ``extra_mappings`` (history.py) and the
bulk content endpoint published the two lists separately without a merged
view, so per-model extra mappings (e.g. ``sensor:ext_temperature_1`` on the
HARDWARIO STICKER Input) never reached instances — even though the model page,
which renders the live merged ``effective_field_mappings``, showed them.
"""

import pytest

from library.exporters import effective_field_mappings_from_config, snapshot_to_schema
from library.history import snapshot_device
from library.models import DeviceType, ProcessorConfig, Vendor, VendorModel

FIELD_MAPPINGS = [
    {"source": "temperature", "target": "env:temperature"},
    {"source": "humidity", "target": "env:humidity"},
]
EXTRA_MAPPINGS = [
    {
        "source": "ext_temperature_1",
        "target": "sensor:ext_temperature_1",
        "tier": "secondary",
        "label": "External Temperature 1",
        "unit": "°C",
    },
    {"source": "voltage", "target": "device:battery_voltage", "tier": "secondary"},
]


class TestEffectiveHelper:
    def test_merges_field_and_extra(self):
        cfg = {"field_mappings": FIELD_MAPPINGS, "extra_mappings": EXTRA_MAPPINGS}
        targets = [e["target"] for e in effective_field_mappings_from_config(cfg)]
        assert "env:temperature" in targets
        assert "sensor:ext_temperature_1" in targets
        assert "device:battery_voltage" in targets
        assert len(targets) == 4

    def test_skips_sourceless_scaffold_rows(self):
        cfg = {
            "field_mappings": [
                {"source": "temperature", "target": "env:temperature"},
                {"target": "env:co2"},  # L2 scaffold row, no source
                {"source": "", "target": "env:pm25"},
            ],
            "extra_mappings": [],
        }
        eff = effective_field_mappings_from_config(cfg)
        assert [e["target"] for e in eff] == ["env:temperature"]

    def test_empty_config(self):
        assert effective_field_mappings_from_config({}) == []


MODBUS_FIELD_MAPPINGS = [
    {"source": "instant_power", "target": "power:active"},
    {"source": "energy_import", "target": "power:total_energy"},
    {"source": "voltage_l1", "target": "elec:voltage_l1"},
]


@pytest.fixture
def modbus_meter_model(db):
    dt, _ = DeviceType.objects.get_or_create(
        code="power_meter_3p",
        defaults={"label": "3-Phase Power Meter", "icon": "zap"},
    )
    vendor = Vendor.objects.create(name="ENEROOO-MB", slug="enerooo-mb")
    model = VendorModel.objects.create(
        vendor=vendor,
        model_number="ER-TEST-M",
        name="Test Modbus Meter",
        device_type="power_meter_3p",
        device_type_fk=dt,
        technology=VendorModel.Technology.MODBUS,
    )
    ProcessorConfig.objects.create(
        device_type=model,
        field_mappings=MODBUS_FIELD_MAPPINGS,
    )
    return model


class TestModbusPublish:
    def test_modbus_decoder_type_is_blank(self, modbus_meter_model):
        # Modbus leaves decoder_type empty by convention (decodes via
        # RegisterDefinition) — this is the precondition for the regression.
        assert modbus_meter_model.processor_config.decoder_type == ""

    def test_modbus_processor_config_survives_publish(self, modbus_meter_model):
        # Regression: snapshot_to_schema gated processor_config on a non-empty
        # decoder_type, silently dropping Modbus field_mappings from the
        # published content — so instances never received the mappings and
        # left every Modbus reading unprocessed.
        snap = snapshot_device(modbus_meter_model)
        schema = snapshot_to_schema(snap)
        assert "processor_config" in schema, (
            "Modbus processor_config dropped from published schema"
        )
        targets = [m["target"] for m in schema["processor_config"]["field_mappings"]]
        assert "power:active" in targets
        # content-API path merges field+extra into the consumed effective list
        eff = effective_field_mappings_from_config(schema["processor_config"])
        assert any(e["target"] == "power:active" for e in eff)


@pytest.fixture
def sticker_model(db):
    dt, _ = DeviceType.objects.get_or_create(
        code="environment_sensor",
        defaults={"label": "Environment Sensor", "icon": "thermometer"},
    )
    vendor = Vendor.objects.create(name="HARDWARIO", slug="hardwario")
    model = VendorModel.objects.create(
        vendor=vendor,
        model_number="STICKER-IN",
        name="HARDWARIO STICKER Input",
        device_type="environment_sensor",
        device_type_fk=dt,
        technology=VendorModel.Technology.LORAWAN,
    )
    ProcessorConfig.objects.create(
        device_type=model,
        extra_config={"measurement_type": "environment"},
        field_mappings=FIELD_MAPPINGS,
        extra_mappings=EXTRA_MAPPINGS,
    )
    return model


class TestPublishChain:
    def test_snapshot_captures_extra_mappings(self, sticker_model):
        snap = snapshot_device(sticker_model)
        assert snap["processor_config"]["extra_mappings"] == EXTRA_MAPPINGS

    def test_chain_preserves_extra_mapping(self, sticker_model):
        # snapshot_device -> snapshot_to_schema -> effective (the content path)
        snap = snapshot_device(sticker_model)
        schema = snapshot_to_schema(snap)
        eff = effective_field_mappings_from_config(schema["processor_config"])
        ext = next(
            (e for e in eff if e["target"] == "sensor:ext_temperature_1"), None
        )
        assert ext is not None
        assert ext["source"] == "ext_temperature_1"
