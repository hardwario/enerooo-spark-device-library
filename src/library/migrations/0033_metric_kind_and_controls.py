"""Schema-v5: L1 Metric ``kind`` + typed ControlConfig ``controls``.

Two parallel additions, both fully additive:

1. ``Metric.kind`` enum (measurement | state) — classifies what role
   the metric plays. ``state`` marks controllable mirrors (relay state,
   target setpoint, HVAC mode) so client UIs can pair them with control
   widgets. Default ``measurement`` keeps every existing row unchanged.
   Seeds three state metrics referenced by the new typed control
   configs below.

2. ``ControlConfig.controls`` typed JSONField — list of structured
   control entries (widget, wire encoding, feedback metric). The
   legacy ``capabilities`` free-form blob stays for backward compat;
   we migrate the three existing ENEROOO smart-plug rows in this
   migration so the typed schema is the canonical one going forward.
"""

from django.db import migrations, models

NEW_STATE_METRICS = [
    # (key, label, unit, data_type, aggregation)
    ("device:relay_state", "Relay State",        "",   "boolean", "last"),
    ("heat:setpoint",      "Target Temperature", "°C", "decimal", "last"),
    ("device:hvac_mode",   "HVAC Mode",          "",   "enum",    "last"),
]


def seed_state_metrics(apps, schema_editor):
    """Seed the L1 catalogue with three ``kind=state`` metrics that
    today's smart plugs and thermostat heads point at.

    Other state metrics (per-device specifics) can be auto-created by
    ``ProcessorConfig.save()`` when an operator wires up controls — same
    tolerant pattern as data metrics.
    """
    Metric = apps.get_model("library", "Metric")
    for key, label, unit, data_type, agg in NEW_STATE_METRICS:
        Metric.objects.update_or_create(
            key=key,
            defaults={
                "label": label,
                "unit": unit,
                "data_type": data_type,
                "aggregation": agg,
                "kind": "state",
            },
        )


def unseed_state_metrics(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    Metric.objects.filter(key__in=[k for k, *_ in NEW_STATE_METRICS]).delete()


def migrate_enerooo_relay_caps(apps, schema_editor):
    """Convert the three ENEROOO smart-plug relay configs from the
    legacy ``capabilities`` blob shape into typed ``controls`` entries.

    Legacy shape::

        {"relay": {"type": "relay", "f_port": 85, "commands": ["on", "off", "toggle"]}}

    Becomes (one typed toggle widget)::

        [{
          "id": "power",
          "label": "Power",
          "widget": "toggle",
          "feedback_metric": "device:relay_state",
          "states": {
            "on":     {"wire": {"f_port": 85, "payload_hex": "01"}},
            "off":    {"wire": {"f_port": 85, "payload_hex": "00"}},
            "toggle": {"wire": {"f_port": 85, "payload_hex": "02"}}
          }
        }]

    Payload bytes are the canonical mapping for the ENEROOO firmware
    (01=on, 00=off, 02=toggle). The legacy ``capabilities`` blob is
    left untouched as a fallback during the transition window.
    """
    ControlConfig = apps.get_model("library", "ControlConfig")
    # Commands → byte mapping for the ENEROOO smart plug firmware.
    PAYLOAD_BY_COMMAND = {"on": "01", "off": "00", "toggle": "02"}

    for cc in ControlConfig.objects.filter(controllable=True):
        caps = cc.capabilities or {}
        relay = caps.get("relay") if isinstance(caps, dict) else None
        if not isinstance(relay, dict) or relay.get("type") != "relay":
            continue
        if cc.controls:
            # Already migrated (idempotent).
            continue
        f_port = relay.get("f_port", 85)
        commands = relay.get("commands") or ["on", "off"]
        states = {}
        for cmd in commands:
            payload = PAYLOAD_BY_COMMAND.get(cmd)
            if not payload:
                continue
            states[cmd] = {"wire": {"f_port": f_port, "payload_hex": payload}}
        if not states:
            continue
        cc.controls = [
            {
                "id": "power",
                "label": "Power",
                "widget": "toggle",
                "feedback_metric": "device:relay_state",
                "states": states,
            }
        ]
        cc.save(update_fields=["controls"])


def revert_enerooo_relay_caps(apps, schema_editor):
    ControlConfig = apps.get_model("library", "ControlConfig")
    for cc in ControlConfig.objects.filter(controllable=True):
        if cc.controls:
            cc.controls = []
            cc.save(update_fields=["controls"])


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0032_metric_aggregation"),
    ]

    operations = [
        migrations.AddField(
            model_name="metric",
            name="kind",
            field=models.CharField(
                choices=[
                    ("measurement", "Measurement"),
                    ("state", "Control state"),
                ],
                default="measurement",
                help_text=(
                    "What role this metric plays: 'measurement' for observed "
                    "quantities (default), 'state' for mirrors of controllable "
                    "device properties paired with a control widget."
                ),
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="controlconfig",
            name="controls",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "List of typed control widgets. Each entry has id/label/"
                    "widget/wire + widget-specific fields. See ControlConfig "
                    "docstring for the full schema."
                ),
            ),
        ),
        migrations.AlterField(
            model_name="controlconfig",
            name="capabilities",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="DEPRECATED — free-form pre-v5 control descriptor. Use ``controls`` instead.",
            ),
        ),
        migrations.RunPython(seed_state_metrics, unseed_state_metrics),
        migrations.RunPython(migrate_enerooo_relay_caps, revert_enerooo_relay_caps),
    ]
