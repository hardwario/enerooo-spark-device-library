"""Schema-v4 follow-up: aggregation enum on L1 Metric.

Adds a single ``aggregation`` field declaring how the metric should
collapse into one value per time bucket — Spark's chart engine and
resample pipeline read this instead of carrying its own hardcoded
mapping. Default ``avg`` covers most instantaneous quantities;
seeded overrides flip the cumulative counters to ``delta`` and the
stateful telemetry to ``last``.

Same denormalization pattern as ``min_value`` / ``max_value`` /
``monotonic`` from 0031 — the value is also inlined into each
``effective_field_mappings`` entry (when non-default) so Spark's
ingest path reads it without a separate L1 lookup.
"""

from django.db import migrations, models

# (key, aggregation) — overrides on top of the ``avg`` default.
SEED_AGGREGATIONS = [
    # Cumulative counters: chart shows period consumption.
    ("heat:total_energy",      "delta"),
    ("heat:total_consumption", "delta"),
    ("heat:total_volume",      "delta"),
    ("water:total_volume",     "delta"),
    ("gas:total_volume",       "delta"),
    ("elec:total_energy",      "delta"),
    # Stateful telemetry: latest reading is more useful than an average.
    ("device:battery",         "last"),
    ("device:battery_voltage", "last"),
    ("device:rssi",            "last"),
    ("device:snr",             "last"),
    ("device:spreading_factor","last"),
    ("device:status",          "last"),
    ("device:firmware",        "last"),
]


def seed_aggregations(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    for key, agg in SEED_AGGREGATIONS:
        Metric.objects.filter(key=key).update(aggregation=agg)


def clear_aggregations(apps, schema_editor):
    Metric = apps.get_model("library", "Metric")
    Metric.objects.filter(key__in=[k for k, _ in SEED_AGGREGATIONS]).update(
        aggregation="avg",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0031_metric_value_bounds"),
    ]

    operations = [
        migrations.AddField(
            model_name="metric",
            name="aggregation",
            field=models.CharField(
                choices=[
                    ("avg", "Average"),
                    ("last", "Last value"),
                    ("delta", "Delta (last − first)"),
                    ("sum", "Sum"),
                    ("min", "Minimum"),
                    ("max", "Maximum"),
                ],
                default="avg",
                help_text=(
                    "How to collapse this metric into one value per time bucket "
                    "in charts. 'delta' for cumulative counters, 'avg' for "
                    "instantaneous quantities, 'last' for state telemetry."
                ),
                max_length=10,
            ),
        ),
        migrations.RunPython(seed_aggregations, clear_aggregations),
    ]
