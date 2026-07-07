"""Seed TTN registration profiles for known LoRaWAN models (Report §4).

Backfill only — sets a field only when it is currently blank, so any value
curated by hand (admin UI / earlier import) is never overwritten. Models not
matched here (⚠ Axioma, Landis+Gyr, HARDWARIO — unverified) keep their blank
defaults; the registrar falls back to its own defaults for those.
"""

from django.db import migrations


def _profile_for(vendor: str, model: str) -> dict | None:
    """TTN profile for a (vendor, model_number) pair, or None if unknown."""
    v, m = vendor.lower(), model.lower()
    if "zenner" in v:
        # All Zenner LRW meters: Class A, shared vendor JoinEUI.
        return {
            "lorawan_version": "MAC_V1_0_3",
            "lorawan_phy_version": "PHY_V1_0_3_REV_A",
            "frequency_plan_id": "EU_863_870_TTN",
            "join_eui_default": "04B6480000000000",
            "device_class": "A",
        }
    if "milesight" in v:
        prof = {
            "lorawan_version": "MAC_V1_0_3",
            "lorawan_phy_version": "PHY_V1_0_3_REV_A",
            "frequency_plan_id": "EU_863_870_TTN",
            "join_eui_default": "24E124C0002A0001",
        }
        if "ws" in m:  # WS513 / WS523 / WS523 FR -> always-on downlink
            prof["device_class"] = "C"
        elif "wt" in m:  # WT101 (= ENEROOO ER10T)
            prof["device_class"] = "A"
        return prof
    if "eastron" in v:
        # SDM630MCT-LR / SDM530-LR: 1.0.2, Class C. JoinEUI unverified -> blank.
        return {
            "lorawan_version": "MAC_V1_0_2",
            "lorawan_phy_version": "PHY_V1_0_2_REV_A",
            "frequency_plan_id": "EU_863_870_TTN",
            "device_class": "C",
        }
    return None


def seed(apps, schema_editor):
    LoRaWANConfig = apps.get_model("library", "LoRaWANConfig")
    for cfg in LoRaWANConfig.objects.select_related("device_type__vendor"):
        vm = cfg.device_type
        vendor = vm.vendor.name if vm and vm.vendor_id else ""
        profile = _profile_for(vendor, vm.model_number if vm else "")
        if not profile:
            continue
        changed = [f for f, val in profile.items() if not getattr(cfg, f)]
        for field in changed:
            setattr(cfg, field, profile[field])
        if changed:
            cfg.save(update_fields=changed)


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0037_lorawanconfig_frequency_plan_id_and_more"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
