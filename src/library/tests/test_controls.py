"""Tests for the v5 typed ControlConfig.controls schema and the
Metric.kind enum that pairs with it."""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError

from library.models import ControlConfig, Metric, Vendor, VendorModel

pytestmark = pytest.mark.django_db


# -----------------------------------------------------------------------------
# Metric.kind
# -----------------------------------------------------------------------------


class TestMetricKind:
    """Kind classifies what role a metric plays — measurement (default,
    observed data) vs state (mirror of a controllable property)."""

    def test_default_kind_is_measurement(self):
        m = Metric.objects.create(key="x:new", label="New", data_type="decimal")
        m.refresh_from_db()
        assert m.kind == "measurement"

    def test_kind_enum_exposes_both_values(self):
        assert Metric.Kind.MEASUREMENT == "measurement"
        assert Metric.Kind.STATE == "state"

    def test_seeded_state_metrics_marked_correctly(self):
        # Migration 0033 seeds three kind=state metrics used by the
        # current smart-plug + thermostat-head control configs.
        for key in ("device:relay_state", "heat:setpoint", "device:hvac_mode"):
            assert Metric.objects.get(key=key).kind == "state", (
                f"{key} should be seeded as kind=state"
            )

    def test_existing_measurement_metrics_unchanged(self):
        # Cumulative + instantaneous metrics were measurement before the
        # 0033 migration and should still be.
        for key in ("heat:total_energy", "env:temperature", "device:battery"):
            assert Metric.objects.get(key=key).kind == "measurement"


# -----------------------------------------------------------------------------
# ControlConfig schema validation
# -----------------------------------------------------------------------------


@pytest.fixture
def smart_plug_vm(db, water_meter_type):
    """A controllable VendorModel we can attach control configs to.

    ``water_meter_type`` is reused as a generic fixture from conftest;
    the device type doesn't matter for these schema tests."""
    vendor = Vendor.objects.create(name="ControlTest", slug="controltest")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="CT-1",
        name="ControlTest CT-1",
        device_type="water_meter",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.LORAWAN,
    )


class TestControlConfigValidation:
    """Each entry in ``ControlConfig.controls`` is validated structurally
    based on its ``widget`` value. Invalid shapes raise ValidationError
    so operators see actionable errors in the admin."""

    def test_empty_controls_is_valid(self, smart_plug_vm):
        cc = ControlConfig(device_type=smart_plug_vm, controllable=False, controls=[])
        cc.full_clean()  # should not raise

    def test_controls_must_be_a_list(self, smart_plug_vm):
        cc = ControlConfig(device_type=smart_plug_vm, controllable=True, controls={"not": "a list"})
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_widget_must_be_known(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{"id": "x", "label": "x", "widget": "frobnicator"}],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_duplicate_ids_rejected(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[
                {"id": "power", "label": "A", "widget": "button", "wire": {"f_port": 1, "payload_hex": "01"}},
                {"id": "power", "label": "B", "widget": "button", "wire": {"f_port": 2, "payload_hex": "02"}},
            ],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    # ---- toggle ----

    def test_toggle_requires_states(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{"id": "p", "label": "P", "widget": "toggle"}],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_toggle_state_requires_wire(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "p",
                "label": "P",
                "widget": "toggle",
                "states": {"on": {"label": "On"}},  # missing wire
            }],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_valid_toggle_passes(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "power",
                "label": "Power",
                "widget": "toggle",
                "feedback_metric": "device:relay_state",
                "states": {
                    "on":  {"wire": {"f_port": 85, "payload_hex": "01"}},
                    "off": {"wire": {"f_port": 85, "payload_hex": "00"}},
                },
            }],
        )
        cc.full_clean()  # should not raise

    # ---- enum ----

    def test_enum_requires_options(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{"id": "mode", "label": "Mode", "widget": "enum"}],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_enum_options_need_value_and_wire(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "mode",
                "label": "Mode",
                "widget": "enum",
                "options": [{"label": "Heat"}],
            }],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_enum_duplicate_values_rejected(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "mode",
                "label": "Mode",
                "widget": "enum",
                "options": [
                    {"value": "heat", "wire": {"f_port": 87, "payload_hex": "01"}},
                    {"value": "heat", "wire": {"f_port": 87, "payload_hex": "02"}},
                ],
            }],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_valid_enum_passes(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "mode",
                "label": "Mode",
                "widget": "enum",
                "feedback_metric": "device:hvac_mode",
                "options": [
                    {"value": "heat", "label": "Heating", "wire": {"f_port": 87, "payload_hex": "01"}},
                    {"value": "cool", "label": "Cooling", "wire": {"f_port": 87, "payload_hex": "02"}},
                ],
            }],
        )
        cc.full_clean()

    # ---- slider ----

    def test_slider_requires_min_max(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{"id": "t", "label": "T", "widget": "slider"}],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_slider_min_must_be_le_max(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "t",
                "label": "T",
                "widget": "slider",
                "min": 30,
                "max": 5,
                "wire": {"f_port": 86, "payload_template": "{value}"},
            }],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_slider_requires_value_binding_in_wire(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "t",
                "label": "T",
                "widget": "slider",
                "min": 5,
                "max": 30,
                "wire": {"f_port": 86},  # no payload_template / register / topic
            }],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_valid_slider_passes(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "target_temp",
                "label": "Target Temperature",
                "widget": "slider",
                "unit": "°C",
                "min": 5,
                "max": 30,
                "step": 0.5,
                "default": 20,
                "feedback_metric": "heat:setpoint",
                "wire": {
                    "f_port": 86,
                    "payload_template": "01{value:02X}",
                    "scale": 2,
                    "offset": 0,
                },
            }],
        )
        cc.full_clean()

    # ---- button ----

    def test_button_requires_wire(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{"id": "id_blink", "label": "Identify", "widget": "button"}],
        )
        with pytest.raises(ValidationError):
            cc.full_clean()

    def test_valid_button_passes(self, smart_plug_vm):
        cc = ControlConfig(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "identify",
                "label": "Identify (blink LED)",
                "widget": "button",
                "wire": {"f_port": 90, "payload_hex": "FF"},
            }],
        )
        cc.full_clean()


# -----------------------------------------------------------------------------
# API sync exposure
# -----------------------------------------------------------------------------


class TestArchetypeExamples:
    """Reference archetype examples surfaced in the admin form must
    always pass the live ``ControlConfig.clean()`` validator — otherwise
    pasting them would yield a form error and the operator would lose
    trust in the templates. This locks the JSON in sync with the schema."""

    def test_all_archetypes_validate(self, smart_plug_vm):
        from library.control_examples import ARCHETYPES

        for arch in ARCHETYPES:
            cc = ControlConfig(
                device_type=smart_plug_vm,
                controllable=True,
                controls=arch["controls"],
            )
            cc.full_clean()  # raises if any example drifts

    def test_archetype_feedback_metrics_exist_when_seeded(self):
        """Examples that reference a non-seeded metric (e.g. valve) must
        flag it in the ``setup`` field so operators know to create the
        L1 row first. Examples whose ``setup`` is None reference only
        seeded metrics."""
        from library.control_examples import ARCHETYPES

        seeded_state_metrics = set(
            Metric.objects.filter(kind="state").values_list("key", flat=True),
        )
        for arch in ARCHETYPES:
            referenced = {
                c["feedback_metric"]
                for c in arch["controls"]
                if c.get("feedback_metric")
            }
            missing = referenced - seeded_state_metrics
            if missing:
                assert arch["setup"], (
                    f"{arch['slug']!r} references unseeded state metric(s) "
                    f"{missing} but has no ``setup`` note for operators."
                )


class TestSyncEndpointControls:
    """``/api/v1/sync/`` exposes the typed ``controls`` list on each
    VendorModel's ``control_config`` block, plus ``kind`` on every L1
    Metric in the top-level ``metrics`` array."""

    @pytest.fixture
    def staff_client(self, db):
        from django.contrib.auth import get_user_model
        from rest_framework.test import APIClient

        User = get_user_model()
        user = User.objects.create_user(
            username="staff-controls",
            password="x",
            is_staff=True,
            is_superuser=True,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_metrics_carry_kind_field(self, staff_client):
        response = staff_client.get("/api/v1/sync/")
        assert response.status_code == 200
        body = response.json()
        by_key = {m["key"]: m for m in body["metrics"]}
        # State metrics flagged correctly
        assert by_key["device:relay_state"]["kind"] == "state"
        assert by_key["heat:setpoint"]["kind"] == "state"
        # Measurement metrics keep the default
        assert by_key["heat:total_energy"]["kind"] == "measurement"
        assert by_key["env:temperature"]["kind"] == "measurement"

    def test_control_config_emits_typed_controls(self, staff_client, smart_plug_vm):
        # Attach a typed toggle to the synthetic model.
        ControlConfig.objects.create(
            device_type=smart_plug_vm,
            controllable=True,
            controls=[{
                "id": "power",
                "label": "Power",
                "widget": "toggle",
                "feedback_metric": "device:relay_state",
                "states": {
                    "on":  {"wire": {"f_port": 85, "payload_hex": "01"}},
                    "off": {"wire": {"f_port": 85, "payload_hex": "00"}},
                },
            }],
        )

        response = staff_client.get("/api/v1/sync/")
        body = response.json()
        vendor_block = next(v for v in body["vendors"] if v["name"] == "ControlTest")
        model = vendor_block["models"][0]
        ctrl_block = model["control_config"]

        assert ctrl_block["controllable"] is True
        assert len(ctrl_block["controls"]) == 1
        assert ctrl_block["controls"][0]["widget"] == "toggle"
        assert ctrl_block["controls"][0]["feedback_metric"] == "device:relay_state"
