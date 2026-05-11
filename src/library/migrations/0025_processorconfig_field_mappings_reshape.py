"""Schema-v4 step 3: collapse the two ProcessorConfig mapping slots into one
and reshape entries to ``{source, metric, transform?, tags?}``.

- Concatenate legacy ``extra_field_mappings`` into ``field_mappings``
  (extras win on same-source collision — preserves the historical effective
  order where extras came after the base).
- Rename per-entry ``target`` → ``metric``.
- Drop per-entry ``unit`` (now resolved from the L1 Metric row).
- Drop per-entry ``primary`` flag (tier now derived from L2 DeviceType.metrics).
- Drop the ``extra_field_mappings`` column from the schema.
- Auto-create any missing L1 Metric rows for ``metric`` values that aren't
  in the seeded catalogue (tolerant migration — operators tidy labels/units
  in admin afterwards).
"""

import django.db.models
from django.db import migrations

FIELD_MAPPINGS_HELP = (
    "L4 — list of {source, metric, scale?, offset?, tags?} entries "
    "mapping this model's decoded fields onto canonical L1 Metric "
    "keys. ``scale`` (default 1) and ``offset`` (default 0) apply "
    "a linear conversion ``value * scale + offset`` — used when "
    "the decoder can't emit canonical units (typically vendor "
    "LoRaWAN codecs we don't fork). ``tags`` distinguishes instances "
    "of the same metric on multi-channel devices (e.g. "
    "{phase: L1} on a 3-phase meter). Entries referencing a metric "
    "key not yet in the L1 catalogue auto-create the Metric row "
    "on save (operators tidy label/unit in admin afterwards)."
)


# Legacy schema-v3 ``transform`` strings that map cleanly to linear
# (scale, offset) pairs. Anything else (``to_float``, ``identity``,
# unknown names) gets dropped on reshape — type coercion isn't part of
# the new model, and Spark already does numeric coercion downstream.
LEGACY_TRANSFORM_TO_LINEAR = {
    "wh_to_kwh": (0.001, 0),
    "mwh_to_kwh": (1000, 0),
    "kwh_to_mwh": (0.001, 0),
    "percent_to_ratio": (0.01, 0),
    "ratio_to_percent": (100, 0),
    "c_to_k": (1, 273.15),
    "k_to_c": (1, -273.15),
}


def _reshape_entry(entry: dict, Metric) -> dict:
    """Rewrite one legacy entry into the new shape.

    Legacy: {source, target, transform?, unit?, primary?, ...}
    New:    {source, metric, scale?, offset?, tags?}
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
    new_entry = {"source": entry.get("source"), "metric": target}

    legacy_transform = entry.get("transform")
    if legacy_transform in LEGACY_TRANSFORM_TO_LINEAR:
        scale, offset = LEGACY_TRANSFORM_TO_LINEAR[legacy_transform]
        if scale != 1:
            new_entry["scale"] = scale
        if offset != 0:
            new_entry["offset"] = offset
    # Any other legacy transform value (e.g. ``to_float``, ``identity``) is
    # silently dropped — type coercion isn't part of the new model.

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
    """Reverse: rebuild legacy {target} entries from {metric}.

    We can't recover the original split between field_mappings and
    extra_field_mappings, or the original transform strings (lossy on
    re-derive) — everything lands back in field_mappings as plain
    target entries.
    """
    ProcessorConfig = apps.get_model("library", "ProcessorConfig")
    for pc in ProcessorConfig.objects.all():
        rebuilt = []
        for entry in pc.field_mappings or []:
            rebuilt.append({
                "source": entry.get("source"),
                "target": entry.get("metric"),
            })
        pc.field_mappings = rebuilt
        pc.save(update_fields=["field_mappings"])


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
