"""Schema-v4 follow-up: value bounds + monotonic flag on L1 Metric.

Adds three optional fields — ``min_value`` / ``max_value`` hard caps
and ``monotonic`` flag — that mirror Spark's existing hardcoded
``METRIC_LIMITS`` and ``NON_NEGATIVE_METRICS`` tables. Seeds
conservative defaults for the standard metrics so Spark can switch
over without an empty-catalogue regression.

Operators tighten the bounds (or leave them null = no opinion) per
metric in the admin. Custom metrics auto-created by
``ProcessorConfig.save()`` start with all bounds null.
"""

from decimal import Decimal

from django.db import migrations, models

# (key, min_value, max_value, monotonic)
SEED_RANGES = [
    # Heat — cumulative counters monotonic, temperatures + flow rates bounded
    ("heat:total_energy",            Decimal("0"),      Decimal("1000000000000"),  True),
    ("heat:total_consumption",       Decimal("0"),      Decimal("1000000000"),     True),
    ("heat:total_volume",            Decimal("0"),      Decimal("1000000000"),     True),
    ("heat:flow_temperature",        Decimal("-50"),    Decimal("500"),            False),
    ("heat:return_temperature",      Decimal("-50"),    Decimal("500"),            False),
    ("heat:flow_rate",               Decimal("-100000"),Decimal("100000"),         False),
    ("heat:consumption_at_set_date", Decimal("0"),      Decimal("1000000000"),     False),
    ("heat:base_consumption",        Decimal("0"),      Decimal("1000000000"),     False),
    # Water
    ("water:total_volume",           Decimal("0"),      Decimal("1000000000"),     True),
    ("water:flow_rate",              Decimal("-100"),   Decimal("1000"),           False),
    # Gas
    ("gas:total_volume",             Decimal("0"),      Decimal("1000000000"),     True),
    ("gas:flow_rate",                Decimal("0"),      Decimal("10000"),          False),
    # Electrical
    ("elec:total_energy",            Decimal("0"),      Decimal("1000000000000"),  True),
    ("elec:active_power",            Decimal("-1000000000"), Decimal("1000000000"),False),
    ("elec:reactive_power",          Decimal("-1000000000"), Decimal("1000000000"),False),
    ("elec:apparent_power",          Decimal("0"),      Decimal("1000000000"),     False),
    ("elec:voltage",                 Decimal("0"),      Decimal("1000"),           False),
    ("elec:current",                 Decimal("0"),      Decimal("10000"),          False),
    ("elec:frequency",               Decimal("0"),      Decimal("100"),            False),
    ("elec:power_factor",            Decimal("-1"),     Decimal("1"),              False),
    # Environment
    ("env:temperature",              Decimal("-100"),   Decimal("150"),            False),
    ("env:humidity",                 Decimal("0"),      Decimal("100"),            False),
    ("env:pressure",                 Decimal("0"),      Decimal("2000"),           False),
    ("env:co2",                      Decimal("0"),      Decimal("50000"),          False),
    # Device telemetry
    ("device:battery",               Decimal("0"),      Decimal("1"),              False),
    ("device:battery_voltage",       Decimal("0"),      Decimal("20"),             False),
    ("device:uptime",                Decimal("0"),      None,                      False),
    # Radio — RSSI / SNR / SF bounded by physics + LoRaWAN spec
    ("device:rssi",                  Decimal("-150"),   Decimal("0"),              False),
    ("device:snr",                   Decimal("-50"),    Decimal("50"),             False),
    ("device:spreading_factor",      Decimal("6"),      Decimal("12"),             False),
]


def seed_ranges(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    for key, mn, mx, mono in SEED_RANGES:
        Metric.objects.filter(key=key).update(
            min_value=mn,
            max_value=mx,
            monotonic=mono,
        )


def clear_ranges(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    Metric.objects.filter(key__in=[k for k, *_ in SEED_RANGES]).update(
        min_value=None,
        max_value=None,
        monotonic=False,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0030_alter_processorconfig_extra_mappings"),
    ]

    operations = [
        migrations.AddField(
            model_name="metric",
            name="min_value",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Hard lower cap. Values < min_value are rejected at ingestion.",
                max_digits=24,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="metric",
            name="max_value",
            field=models.DecimalField(
                blank=True,
                decimal_places=6,
                help_text="Hard upper cap. Values > max_value are rejected at ingestion.",
                max_digits=24,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="metric",
            name="monotonic",
            field=models.BooleanField(
                default=False,
                help_text="True for cumulative counters that must not decrease (e.g. total_energy, total_volume).",
            ),
        ),
        migrations.RunPython(seed_ranges, clear_ranges),
    ]
