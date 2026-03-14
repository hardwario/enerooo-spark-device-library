"""Device history helpers — snapshot, diff, and recording."""

import logging

from .models import DeviceHistory

logger = logging.getLogger(__name__)


def snapshot_device(device):
    """Serialize a VendorModel and all related configs into a JSON-safe dict."""
    data = {
        "key": str(device.key),
        "vendor_key": str(device.vendor.key) if device.vendor else None,
        "vendor": device.vendor.name if device.vendor else None,
        "model_number": device.model_number,
        "name": device.name,
        "device_type": device.device_type,
        "technology": device.technology,
        "description": device.description,
    }

    # Modbus config
    try:
        mc = device.modbus_config
        data["modbus_config"] = {
            "function": mc.function,
            "byte_order": mc.byte_order,
            "word_order": mc.word_order,
        }
        data["registers"] = [
            {
                "field_name": r.field_name,
                "field_unit": r.field_unit,
                "address": r.address,
                "data_type": r.data_type,
                "scale": r.scale,
                "offset": r.offset,
            }
            for r in mc.register_definitions.all().order_by("address")
        ]
    except Exception:
        pass

    # LoRaWAN config
    try:
        lc = device.lorawan_config
        data["lorawan_config"] = {
            "device_class": lc.device_class,
            "downlink_f_port": lc.downlink_f_port,
            "payload_codec": lc.payload_codec,
            "field_map": lc.field_map,
        }
    except Exception:
        pass

    # wM-Bus config
    try:
        wc = device.wmbus_config
        data["wmbus_config"] = {
            "manufacturer_code": wc.manufacturer_code,
            "wmbus_device_type": wc.wmbus_device_type,
            "data_record_mapping": wc.data_record_mapping,
            "encryption_required": wc.encryption_required,
            "shared_encryption_key": wc.shared_encryption_key,
            "wmbusmeters_driver": wc.wmbusmeters_driver,
            "field_map": wc.field_map,
        }
    except Exception:
        pass

    # Control config
    try:
        cc = device.control_config
        data["control_config"] = {
            "controllable": cc.controllable,
            "capabilities": cc.capabilities,
        }
    except Exception:
        pass

    # Processor config
    try:
        pc = device.processor_config
        data["processor_config"] = {
            "decoder_type": pc.decoder_type,
        }
    except Exception:
        pass

    return data


def diff_snapshots(old, new):
    """Compare two snapshots and return a dict of changes.

    Returns: {field: {"old": ..., "new": ...}} for changed fields.
    Registers are diffed structurally as a list.
    """
    if not old:
        return {}

    changes = {}
    all_keys = set(old.keys()) | set(new.keys())

    _config_keys = {"modbus_config", "lorawan_config", "wmbus_config", "control_config", "processor_config"}

    for key in all_keys:
        old_val = old.get(key)
        new_val = new.get(key)

        if old_val == new_val:
            continue

        if key == "registers":
            reg_diff = _diff_registers(old_val or [], new_val or [])
            if reg_diff:
                changes["registers"] = reg_diff
        elif key in _config_keys and isinstance(old_val, dict) and isinstance(new_val, dict):
            # Break nested config dicts into sub-field changes
            sub_keys = set(old_val.keys()) | set(new_val.keys())
            for sk in sub_keys:
                ov = old_val.get(sk)
                nv = new_val.get(sk)
                if ov != nv:
                    label = f"{key}.{sk}"
                    changes[label] = {"old": ov, "new": nv}
        else:
            changes[key] = {"old": old_val, "new": new_val}

    return changes


def _diff_registers(old_regs, new_regs):
    """Diff two lists of register dicts.

    Returns a dict with added, removed, and modified register entries.
    Registers are matched by address.
    """
    old_by_addr = {r["address"]: r for r in old_regs}
    new_by_addr = {r["address"]: r for r in new_regs}

    added = [r for addr, r in new_by_addr.items() if addr not in old_by_addr]
    removed = [r for addr, r in old_by_addr.items() if addr not in new_by_addr]
    modified = []

    for addr in set(old_by_addr) & set(new_by_addr):
        if old_by_addr[addr] != new_by_addr[addr]:
            modified.append({
                "address": addr,
                "old": old_by_addr[addr],
                "new": new_by_addr[addr],
            })

    result = {}
    if added:
        result["added"] = added
    if removed:
        result["removed"] = removed
    if modified:
        result["modified"] = modified
    return result


def record_history(device, action, user, previous_snapshot=None):
    """Take a snapshot and create a DeviceHistory entry.

    Args:
        device: VendorModel instance.
        action: One of DeviceHistory.Action values.
        user: The user performing the action.
        previous_snapshot: Snapshot dict from before the change (for diffs).

    Returns:
        DeviceHistory instance or None on error.
    """
    try:
        current_snapshot = snapshot_device(device)

        # Compute version number
        last_version = (
            DeviceHistory.objects.filter(device=device)
            .order_by("-version")
            .values_list("version", flat=True)
            .first()
        )
        version = (last_version or 0) + 1

        # Compute diff
        changes = {}
        if previous_snapshot and action != DeviceHistory.Action.CREATED:
            changes = diff_snapshots(previous_snapshot, current_snapshot)

        return DeviceHistory.objects.create(
            device=device,
            device_label=str(device),
            version=version,
            action=action,
            user=user if user and user.is_authenticated else None,
            snapshot=current_snapshot,
            changes=changes,
        )
    except Exception:
        logger.exception("Failed to record device history")
        return None
