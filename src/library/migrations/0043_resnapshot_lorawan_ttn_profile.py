"""Re-snapshot LoRaWAN models so the TTN profile fields reach publishes.

``snapshot_device`` historically omitted the TTN registration profile fields
(lorawan_version / lorawan_phy_version / frequency_plan_id / join_eui_default /
supports_join), so every published version served them empty even after the
values were filled in the portal. The code fix adds them to new snapshots;
this migration records a fresh history entry for every LoRaWAN model so the
next publish picks up complete snapshots instead of the stale ones.
"""

from django.db import migrations


def resnapshot_lorawan_models(apps, schema_editor):
    # Fresh databases (tests, new deploys) have nothing to re-snapshot. Bail
    # out via the historical model before touching the live one below, whose
    # columns from later migrations do not exist yet at this point.
    if not apps.get_model("library", "VendorModel").objects.filter(technology="lorawan").exists():
        return

    # Runtime imports on purpose: snapshotting needs the real model methods
    # and helpers, not historical models (same pattern as the 0038 seed).
    from library.history import record_history
    from library.models import DeviceHistory, VendorModel

    for device in VendorModel.objects.filter(technology="lorawan"):
        record_history(device, DeviceHistory.Action.UPDATED, None)


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0042_remove_lorawanconfig_field_map_and_more"),
    ]

    operations = [
        migrations.RunPython(resnapshot_lorawan_models, migrations.RunPython.noop),
    ]
