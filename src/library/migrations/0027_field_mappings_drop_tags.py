"""Schema-v4 follow-up: drop per-entry ``tags`` from L4 field_mappings.

Multi-channel devices now model each channel as a separate L1 metric
(``elec:voltage_l1`` / ``elec:voltage_l2`` / …) instead of one metric
disambiguated by a ``tags`` dict. Simpler, no parallel concept to learn.
"""

from django.db import migrations


def strip_tags(apps, schema_editor):
    ProcessorConfig = apps.get_model("library", "ProcessorConfig")
    for pc in ProcessorConfig.objects.exclude(field_mappings=[]):
        cleaned = []
        changed = False
        for entry in pc.field_mappings or []:
            if "tags" in entry:
                cleaned.append({k: v for k, v in entry.items() if k != "tags"})
                changed = True
            else:
                cleaned.append(entry)
        if changed:
            pc.field_mappings = cleaned
            pc.save(update_fields=["field_mappings"])


def noop(apps, schema_editor):
    return


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0026_field_mappings_rename_metric_to_target"),
    ]

    operations = [
        migrations.RunPython(strip_tags, noop),
    ]
