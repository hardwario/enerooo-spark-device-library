"""AlarmConfig must survive the publish -> content-sync path.

``AlarmConfig`` is a peer config object (sibling of ControlConfig): a distinct
concern from measurement normalization, feeding the alerting system. Its
``mappings`` carry severity + description per status flag (no L1 target).
"""

import pytest

from library.exporters import snapshot_to_schema
from library.forms import AlarmConfigForm
from library.history import snapshot_device
from library.models import AlarmConfig, DeviceType, Vendor, VendorModel

ALARM_MAPPINGS = [
    {
        "source": "status",
        "match": "SENSOR_T1_OUTSIDE_MEASURING_RANGE",
        "severity": "warning",
        "description": "Sensor T1 outside measuring range",
    },
    {
        "match": "LEAKAGE_HOT_WATER",
        "severity": "critical",
        "description": "Hot water leakage detected",
    },
]


@pytest.fixture
def wmbus_model(db):
    dt, _ = DeviceType.objects.get_or_create(
        code="heat_meter",
        defaults={"label": "Heat Meter", "icon": "flame"},
    )
    vendor = Vendor.objects.create(name="Kaden", slug="kaden")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="D10",
        name="Kaden D10",
        device_type="heat_meter",
        device_type_fk=dt,
        technology=VendorModel.Technology.WMBUS,
    )


class TestPublishChain:
    def test_snapshot_captures_alarm_config(self, wmbus_model):
        AlarmConfig.objects.create(device_type=wmbus_model, mappings=ALARM_MAPPINGS)
        snap = snapshot_device(wmbus_model)
        assert snap["alarm_config"]["mappings"] == ALARM_MAPPINGS

        schema = snapshot_to_schema(snap)
        assert schema["alarm_config"]["mappings"] == ALARM_MAPPINGS

    def test_alarm_config_independent_of_processor_config(self, wmbus_model):
        # A model can carry alarm mappings with no field/processor config at all.
        AlarmConfig.objects.create(device_type=wmbus_model, mappings=ALARM_MAPPINGS)
        snap = snapshot_device(wmbus_model)
        schema = snapshot_to_schema(snap)
        assert "alarm_config" in schema
        # No processor_config was created → it must not be fabricated.
        assert "processor_config" not in schema

    def test_empty_mappings_not_published(self, wmbus_model):
        AlarmConfig.objects.create(device_type=wmbus_model, mappings=[])
        snap = snapshot_device(wmbus_model)
        schema = snapshot_to_schema(snap)
        assert "alarm_config" not in schema


class TestFormValidation:
    def _form(self, wmbus_model, mappings):
        import json

        ac, _ = AlarmConfig.objects.get_or_create(device_type=wmbus_model)
        return AlarmConfigForm(data={"mappings": json.dumps(mappings)}, instance=ac)

    def test_valid_entries_pass(self, wmbus_model):
        form = self._form(wmbus_model, ALARM_MAPPINGS)
        assert form.is_valid(), form.errors

    def test_missing_match_rejected(self, wmbus_model):
        form = self._form(wmbus_model, [{"severity": "warning"}])
        assert not form.is_valid()
        assert "match" in str(form.errors)

    def test_bad_severity_rejected(self, wmbus_model):
        form = self._form(wmbus_model, [{"match": "X", "severity": "fatal"}])
        assert not form.is_valid()
        assert "severity" in str(form.errors)
