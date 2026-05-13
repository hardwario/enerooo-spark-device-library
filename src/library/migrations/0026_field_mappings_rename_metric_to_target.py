"""Schema-v4 follow-up: rename L4 entry key ``metric`` → ``target``.

The previous reshape migration (0025) renamed legacy ``target`` to
``metric`` for semantic clarity. We've reverted that decision so existing
decoder code (notably Spark's ``library_config.py``, which reads
``entry["target"]``) keeps working without a code change downstream. The
L1 Metric model + L2 DeviceType.metrics entries are unaffected — the
rename applies only to L4 ``ProcessorConfig.field_mappings`` entries.
"""

from django.db import migrations


def rename_metric_to_target(apps, schema_editor):
    ProcessorConfig = apps.get_model("library", "ProcessorConfig")
    for pc in ProcessorConfig.objects.exclude(field_mappings=[]):
        rebuilt = []
        changed = False
        for entry in pc.field_mappings or []:
            if "metric" in entry and "target" not in entry:
                new_entry = {k: v for k, v in entry.items() if k != "metric"}
                new_entry["target"] = entry["metric"]
                rebuilt.append(new_entry)
                changed = True
            else:
                rebuilt.append(entry)
        if changed:
            pc.field_mappings = rebuilt
            pc.save(update_fields=["field_mappings"])


def rename_target_to_metric(apps, schema_editor):
    ProcessorConfig = apps.get_model("library", "ProcessorConfig")
    for pc in ProcessorConfig.objects.exclude(field_mappings=[]):
        rebuilt = []
        changed = False
        for entry in pc.field_mappings or []:
            if "target" in entry and "metric" not in entry:
                new_entry = {k: v for k, v in entry.items() if k != "target"}
                new_entry["metric"] = entry["target"]
                rebuilt.append(new_entry)
                changed = True
            else:
                rebuilt.append(entry)
        if changed:
            pc.field_mappings = rebuilt
            pc.save(update_fields=["field_mappings"])


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0025_processorconfig_field_mappings_reshape"),
    ]

    operations = [
        migrations.RunPython(rename_metric_to_target, rename_target_to_metric),
    ]
