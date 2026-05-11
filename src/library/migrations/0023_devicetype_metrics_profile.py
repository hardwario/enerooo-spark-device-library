"""Schema-v4 step 2: replace DeviceType.default_field_mappings with .metrics.

The old field carried source→target mappings (a hybrid of taxonomy and
decoder defaults). The new ``metrics`` field is purely the L2 semantic
profile: ``[{metric, tier}]`` — which canonical metrics this type tracks
and at what render tier.

Data migration extracts unique ``target`` values from each type's old
default_field_mappings and seeds them into the new ``metrics`` field
with tier=secondary by default (operators promote to primary in admin
after the migration). The old ``default_field_mappings`` field is then
dropped.
"""

import django.db.models
from django.db import migrations

METRICS_HELP = (
    "L2 profile — list of {metric, tier} entries declaring which "
    "L1 Metric keys this device type tracks, and at which display "
    "tier. Tier ∈ {primary, secondary, diagnostic}. No sources or "
    "transforms here — those are decoder concerns on VendorModel."
)


def migrate_defaults_to_metrics(apps, schema_editor):
    """Convert existing default_field_mappings into metrics entries.

    Aggregates unique target values per DeviceType into a deduplicated
    list of {metric, tier=secondary}. Operators promote to primary in
    admin after migration. Also auto-creates any L1 Metric rows missing
    from the seeded catalogue (tolerant migration — see redesign doc).
    """
    DeviceType = apps.get_model("library", "DeviceType")
    Metric = apps.get_model("library", "Metric")

    for dt in DeviceType.objects.all():
        seen = set()
        profile = []
        for entry in dt.default_field_mappings or []:
            target = entry.get("target")
            if not target or target in seen:
                continue
            seen.add(target)
            # Auto-create the L1 Metric row if it isn't seeded yet.
            Metric.objects.get_or_create(
                key=target,
                defaults={
                    "label": target.split(":", 1)[-1].replace("_", " ").title(),
                    "unit": entry.get("unit", "") or "",
                    "data_type": "decimal",
                },
            )
            tier = "primary" if entry.get("primary") else "secondary"
            profile.append({"metric": target, "tier": tier})
        if profile:
            dt.metrics = profile
            dt.save(update_fields=["metrics"])


def revert_metrics_to_defaults(apps, schema_editor):
    """Reverse: rebuild a minimal default_field_mappings from metrics.

    We can't recover the original source/transform — only the targets.
    Tier promotes back to primary flag.
    """
    DeviceType = apps.get_model("library", "DeviceType")
    for dt in DeviceType.objects.all():
        rebuilt = [
            {"target": entry["metric"], "primary": entry.get("tier") == "primary"}
            for entry in (dt.metrics or [])
        ]
        dt.default_field_mappings = rebuilt
        dt.save(update_fields=["default_field_mappings"])


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0022_metric_catalogue"),
    ]

    operations = [
        migrations.AddField(
            model_name="devicetype",
            name="metrics",
            field=django.db.models.JSONField(
                blank=True, default=list, help_text=METRICS_HELP,
            ),
        ),
        migrations.RunPython(migrate_defaults_to_metrics, revert_metrics_to_defaults),
        migrations.RemoveField(
            model_name="devicetype",
            name="default_field_mappings",
        ),
    ]
