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
        decoder_type=ProcessorConfig.DecoderType.JS_CODEC,
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
