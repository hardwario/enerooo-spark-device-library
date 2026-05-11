"""Schema-v4 step 3: collapse the two ProcessorConfig mapping slots into one
and reshape entries to ``{source, target, scale?, offset?, tags?}``.

- Concatenate legacy ``extra_field_mappings`` into ``field_mappings``
  (extras win on same-source collision — preserves the historical effective
  order where extras came after the base).
- Keep per-entry ``target`` (now references an L1 Metric.key — Spark and
  other consumers continue to read ``entry["target"]`` unchanged).
- Drop per-entry ``unit`` (now resolved from the L1 Metric row).
- Drop per-entry ``primary`` flag (tier now derived from L2 DeviceType.metrics).
- Drop per-entry ``transform`` (production data only ever carried type-coercion
  values like ``to_float``; unit conversion is now expressed via ``scale``/``offset``).
- Drop the ``extra_field_mappings`` column from the schema.
- Auto-create any missing L1 Metric rows for ``target`` values that aren't
  in the seeded catalogue (tolerant migration — operators tidy labels/units
  in admin afterwards).
"""

import django.db.models
from django.db import migrations

FIELD_MAPPINGS_HELP = (
    "L4 — list of {source, target, scale?, offset?, tags?} entries "
    "mapping this model's decoded fields onto canonical L1 Metric "
    "keys (``target`` is the Metric.key being pointed at). "
    "``scale`` (default 1) and ``offset`` (default 0) apply "
    "a linear conversion ``value * scale + offset`` — used when "
    "the decoder can't emit canonical units (typically vendor "
    "LoRaWAN codecs we don't fork). ``tags`` distinguishes instances "
    "of the same metric on multi-channel devices (e.g. "
    "{phase: L1} on a 3-phase meter). Entries referencing a target "
    "key not yet in the L1 catalogue auto-create the Metric row "
    "on save (operators tidy label/unit in admin afterwards)."
)


def _reshape_entry(entry: dict, Metric) -> dict:
    """Rewrite one legacy entry into the new shape.

    Legacy: {source, target, transform?, unit?, primary?, ...}
    New:    {source, target, scale?, offset?, tags?}
    """
    target = entry.get("target") or entry.get("metric")
    if not target:
        return entry  # malformed — leave alone, validation will surface
    Metric.objects.get_or_create(
        key=target,
        defaults={
            "label": target.split(":", 1)[-1].replace("_", " ").title(),
            "unit": entry.get("unit", "") or "",
            "data_type": "decimal",
        },
    )
    new_entry = {"source": entry.get("source"), "target": target}
    if entry.get("scale") not in (None, 1):
        new_entry["scale"] = entry["scale"]
    if entry.get("offset") not in (None, 0):
        new_entry["offset"] = entry["offset"]
    if entry.get("tags"):
        new_entry["tags"] = entry["tags"]
    return new_entry


def reshape_processor_field_mappings(apps, schema_editor):
    ProcessorConfig = apps.get_model("library", "ProcessorConfig")
    Metric = apps.get_model("library", "Metric")
    for pc in ProcessorConfig.objects.all():
        base = list(pc.field_mappings or [])
        extras = list(pc.extra_field_mappings or [])
        # Collapse extras into base (extras win on same source collision —
        # preserves the historical effective-list order).
        if extras:
            extra_sources = {e.get("source") for e in extras if e.get("source")}
            base = [m for m in base if m.get("source") not in extra_sources] + extras
        # Reshape each entry to the new schema.
        pc.field_mappings = [_reshape_entry(e, Metric) for e in base]
        pc.save(update_fields=["field_mappings"])


def revert_reshape(apps, schema_editor):
    """Reverse: shape barely changes (target stays target). The split between
    field_mappings and extra_field_mappings and the original transform
    strings can't be recovered lossless — everything lands back in
    field_mappings."""
    return


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0024_alter_libraryversion_schema_version"),
    ]

    operations = [
        migrations.RunPython(reshape_processor_field_mappings, revert_reshape),
        migrations.RemoveField(
            model_name="processorconfig",
            name="extra_field_mappings",
        ),
        migrations.AlterField(
            model_name="processorconfig",
            name="field_mappings",
            field=django.db.models.JSONField(
                blank=True, default=list, help_text=FIELD_MAPPINGS_HELP,
            ),
        ),
    ]
