"""Schema-v5 cleanup: drop the deprecated ``ControlConfig.capabilities``
free-form JSON field.

The previous migration (0033) populated the typed ``controls`` list
from the legacy ``{relay: ...}`` blob and kept ``capabilities``
populated as a backward-compat fallback. With no external consumer
still reading that field — confirmed before this migration was
authored — we can drop the column outright.

Data already migrated:
- Three ENEROOO smart plugs (ER10W / ER11W / ER13W) carry the typed
  ``power`` toggle in ``controls`` (see 0033 RunPython).
- No other rows used ``capabilities`` in production.

Irreversible without restoring the (already-superseded) legacy data —
the reverse op is a no-op AddField with default ``{}`` so a rollback
gives back an empty column rather than the original blob.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0033_metric_kind_and_controls"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="controlconfig",
            name="capabilities",
        ),
    ]
