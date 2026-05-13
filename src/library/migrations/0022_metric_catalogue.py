"""Schema-v4 step 1: introduce the L1 Metric catalogue.

The seed list is intentionally conservative — only metrics we observe in
the current device library data plus the most-common cross-domain ones
(battery, signal strength). Operators extend the catalogue from the admin
once new metrics appear in vendor decoders.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.db import migrations, models

SEED_METRICS = [
    # Heat domain
    ("heat:total_energy",            "Total Energy",            "kWh",     "decimal"),
    ("heat:total_consumption",       "Total Consumption",       "HCA",     "integer"),
    ("heat:total_volume",            "Total Volume",            "m³",      "decimal"),
    ("heat:flow_temperature",        "Flow Temperature",        "°C",      "decimal"),
    ("heat:return_temperature",      "Return Temperature",      "°C",      "decimal"),
    ("heat:flow_rate",               "Flow Rate",               "m³/h",    "decimal"),
    ("heat:consumption_at_set_date", "Consumption at Set Date", "HCA",     "integer"),
    ("heat:base_consumption",        "Base Consumption",        "HCA",     "integer"),
    # Water domain
    ("water:total_volume",           "Total Volume",            "m³",      "decimal"),
    ("water:flow_rate",              "Flow Rate",               "m³/h",    "decimal"),
    # Gas domain
    ("gas:total_volume",             "Total Volume",            "m³",      "decimal"),
    ("gas:flow_rate",                "Flow Rate",               "m³/h",    "decimal"),
    # Electrical domain
    ("elec:total_energy",            "Total Active Energy",     "kWh",     "decimal"),
    ("elec:active_power",            "Active Power",            "W",       "decimal"),
    ("elec:reactive_power",          "Reactive Power",          "var",     "decimal"),
    ("elec:apparent_power",          "Apparent Power",          "VA",      "decimal"),
    ("elec:voltage",                 "Voltage",                 "V",       "decimal"),
    ("elec:current",                 "Current",                 "A",       "decimal"),
    ("elec:frequency",               "Frequency",               "Hz",      "decimal"),
    ("elec:power_factor",            "Power Factor",            "",        "decimal"),
    # Environment domain
    ("env:temperature",              "Temperature",             "°C",      "decimal"),
    ("env:humidity",                 "Humidity",                "%",       "decimal"),
    ("env:pressure",                 "Pressure",                "hPa",     "decimal"),
    ("env:co2",                      "CO₂",                     "ppm",     "decimal"),
    # Cross-domain — device health + radio (all under device:* — we don't
    # fragment the namespace per technology; RSSI / SNR are device telemetry
    # for any wireless device, just like battery is universal).
    ("device:battery",               "Battery",                 "ratio",   "decimal"),
    ("device:battery_voltage",       "Battery Voltage",         "V",       "decimal"),
    ("device:firmware_version",      "Firmware Version",        "",        "enum"),
    ("device:uptime",                "Uptime",                  "s",       "integer"),
    ("device:status",                "Status",                  "",        "enum"),
    ("device:rssi",                  "Signal Strength",         "dBm",     "integer"),
    ("device:snr",                   "Signal-to-Noise Ratio",   "dB",      "decimal"),
    ("device:spreading_factor",      "Spreading Factor",        "",        "integer"),
]


def seed_metrics(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    for key, label, unit, data_type in SEED_METRICS:
        Metric.objects.get_or_create(
            key=key,
            defaults={"label": label, "unit": unit, "data_type": data_type},
        )


def unseed_metrics(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    Metric.objects.filter(key__in=[k for k, _, _, _ in SEED_METRICS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0021_schema_v3"),
    ]

    operations = [
        migrations.CreateModel(
            name="Metric",
            fields=[
                ("created", model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, verbose_name="created")),
                ("modified", model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, verbose_name="modified")),
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("key", models.CharField(help_text="Namespaced canonical key, e.g. 'heat:total_energy'. Format '<namespace>:<name>'.", max_length=128, unique=True)),
                ("label", models.CharField(max_length=128)),
                ("unit", models.CharField(blank=True, default="", help_text="Canonical unit symbol, e.g. 'kWh', 'm³', 'dBm'. Empty for dimensionless metrics.", max_length=32)),
                ("data_type", models.CharField(choices=[("decimal", "Decimal"), ("integer", "Integer"), ("boolean", "Boolean"), ("enum", "Enum")], default="decimal", max_length=20)),
                ("description", models.TextField(blank=True, default="")),
            ],
            options={"ordering": ["key"]},
        ),
        migrations.RunPython(seed_metrics, unseed_metrics),
    ]
