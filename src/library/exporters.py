"""YAML export logic for device definitions."""

import logging
from pathlib import Path

import yaml

from .models import DEFAULT_SCHEMA_VERSION, DeviceType, Vendor, VendorModel

logger = logging.getLogger(__name__)


def export_to_yaml(output_dir: str | Path) -> dict:
    """Export all device definitions to YAML files.

    Returns a dict with export statistics.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stats = {
        "vendors_exported": 0,
        "devices_exported": 0,
        "device_types_exported": 0,
    }

    manifest_vendors = []

    for vendor in Vendor.objects.prefetch_related("device_types").all():
        devices = vendor.device_types.all()
        if not devices.exists():
            continue

        device_types = []
        for device in devices:
            device_types.append(_export_device(device))

        vendor_data = {"models": device_types}

        filename = f"{vendor.slug}.yaml"
        file_path = output_dir / filename
        with open(file_path, "w") as f:
            yaml.dump(vendor_data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

        manifest_vendors.append({
            "name": vendor.name,
            "file": filename,
        })

        stats["vendors_exported"] += 1
        stats["devices_exported"] += len(device_types)
        logger.info("Exported %d devices for %s", len(device_types), vendor.name)

    # Schema-v3: device_types section carries shared per-type metadata
    # (offline window, primary / secondary fields, icon). Importers without
    # v3 awareness ignore the section.
    device_type_entries = [_export_device_type(dt) for dt in DeviceType.objects.all()]
    stats["device_types_exported"] = len(device_type_entries)

    # Export manifest
    from .models import LibraryVersion

    current_version = LibraryVersion.objects.filter(is_current=True).first()
    manifest = {
        "version": current_version.version if current_version else "0.0.0",
        "schema_version": current_version.schema_version if current_version else DEFAULT_SCHEMA_VERSION,
        "device_types": device_type_entries,
        "vendors": manifest_vendors,
    }

    manifest_path = output_dir.parent / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return stats


def _export_device_type(dt: DeviceType) -> dict:
    """Export a single DeviceType row to a YAML-compatible dict."""
    return {
        "code": dt.code,
        "key": str(dt.key) if dt.key else "",
        "label": dt.label,
        "description": dt.description or "",
        "icon": dt.icon or "",
        "default_field_mappings": list(dt.default_field_mappings or []),
    }


def _export_device(device: VendorModel) -> dict:
    """Export a single device type to a YAML-compatible dict."""
    data = {
        "vendor_name": device.vendor.name,
        "model_number": device.model_number,
        "name": device.name,
        "device_type": device.device_type,
        "description": device.description or "",
        "technology_config": _export_tech_config(device),
        "control_config": _export_control_config(device),
        "processor_config": _export_processor_config(device),
    }
    # Schema-v3: device_type_key points into the manifest's device_types
    # section. Old importers that ignore the field still see ``device_type``
    # (the enum string) and resolve type metadata via that.
    if device.device_type_fk_id and device.device_type_fk.key:
        data["device_type_key"] = str(device.device_type_fk.key)

    # Schema-v3 per-meter knob. Only emitted when set so the YAML stays
    # tidy for the common "inherit from the type" case.
    if device.offline_window_seconds is not None:
        data["offline_window_seconds"] = device.offline_window_seconds
    return data


def _export_tech_config(device: VendorModel) -> dict:
    """Export technology-specific config."""
    config = {"technology": device.technology}

    if device.technology == "modbus":
        try:
            modbus = device.modbus_config
            if modbus.function:
                config["function"] = modbus.function
            if modbus.byte_order:
                config["byte_order"] = modbus.byte_order
            if modbus.word_order:
                config["word_order"] = modbus.word_order

            registers = []
            for reg in modbus.register_definitions.all():
                registers.append({
                    "field": {
                        "name": reg.field_name,
                        "unit": reg.field_unit,
                    },
                    "scale": reg.scale,
                    "offset": reg.offset,
                    "address": reg.address,
                    "data_type": reg.data_type,
                })
            if registers:
                config["register_definitions"] = registers
        except VendorModel.modbus_config.RelatedObjectDoesNotExist:
            pass

    elif device.technology == "lorawan":
        try:
            lorawan = device.lorawan_config
            if lorawan.device_class:
                config["device_class"] = lorawan.device_class
            if lorawan.downlink_f_port is not None:
                config["downlink_f_port"] = lorawan.downlink_f_port
            if lorawan.payload_codec:
                config["payload_codec"] = {
                    "format": lorawan.codec_format or "ttn_v3",
                    "script": lorawan.payload_codec,
                }
            if lorawan.field_map:
                config["field_map"] = lorawan.field_map
        except VendorModel.lorawan_config.RelatedObjectDoesNotExist:
            pass

    elif device.technology == "wmbus":
        try:
            wmbus = device.wmbus_config
            config["manufacturer_code"] = wmbus.manufacturer_code
            if wmbus.wmbus_version:
                config["wmbus_version"] = wmbus.wmbus_version
            config["wmbus_device_type"] = wmbus.wmbus_device_type
            config["data_record_mapping"] = wmbus.data_record_mapping
            config["encryption_required"] = wmbus.encryption_required
            if wmbus.shared_encryption_key:
                config["shared_encryption_key"] = wmbus.shared_encryption_key
            if wmbus.wmbusmeters_driver:
                config["wmbusmeters_driver"] = wmbus.wmbusmeters_driver
            if wmbus.field_map:
                config["field_map"] = wmbus.field_map
            if wmbus.is_mvt_default:
                config["is_mvt_default"] = wmbus.is_mvt_default
        except VendorModel.wmbus_config.RelatedObjectDoesNotExist:
            pass

    return config


def _export_control_config(device: VendorModel) -> dict:
    """Export control config."""
    try:
        ctrl = device.control_config
        return {
            "capabilities": ctrl.capabilities,
            "controllable": ctrl.controllable,
        }
    except VendorModel.control_config.RelatedObjectDoesNotExist:
        return {}


def _export_processor_config(device: VendorModel) -> dict:
    """Export processor config."""
    try:
        proc = device.processor_config
        config = {}
        if proc.decoder_type:
            config["decoder_type"] = proc.decoder_type
        if proc.extra_config:
            config["extra_config"] = proc.extra_config
        if proc.field_mappings:
            config["field_mappings"] = proc.field_mappings
        if proc.extra_field_mappings:
            config["extra_field_mappings"] = proc.extra_field_mappings
        return config
    except VendorModel.processor_config.RelatedObjectDoesNotExist:
        pass
    return {}


def snapshot_to_schema(snapshot: dict) -> dict:
    """Convert a DeviceHistory snapshot dict to the YAML device schema format."""
    technology = snapshot.get("technology", "")

    tech_config = {"technology": technology}
    if technology == "modbus":
        mc = snapshot.get("modbus_config", {})
        if mc.get("function"):
            tech_config["function"] = mc["function"]
        if mc.get("byte_order"):
            tech_config["byte_order"] = mc["byte_order"]
        if mc.get("word_order"):
            tech_config["word_order"] = mc["word_order"]
        registers = snapshot.get("registers", [])
        if registers:
            tech_config["register_definitions"] = [
                {
                    "field": {"name": r["field_name"], "unit": r.get("field_unit", "")},
                    "scale": r.get("scale", 1.0),
                    "offset": r.get("offset", 0.0),
                    "address": r["address"],
                    "data_type": r.get("data_type", "uint16"),
                }
                for r in registers
            ]
    elif technology == "lorawan":
        lc = snapshot.get("lorawan_config", {})
        if lc.get("device_class"):
            tech_config["device_class"] = lc["device_class"]
        if lc.get("downlink_f_port") is not None:
            tech_config["downlink_f_port"] = lc["downlink_f_port"]
        if lc.get("payload_codec"):
            tech_config["payload_codec"] = {
                "format": lc.get("codec_format", "ttn_v3"),
                "script": lc["payload_codec"],
            }
        if lc.get("field_map"):
            tech_config["field_map"] = lc["field_map"]
    elif technology == "wmbus":
        wc = snapshot.get("wmbus_config", {})
        tech_config["manufacturer_code"] = wc.get("manufacturer_code", "")
        if wc.get("wmbus_version"):
            tech_config["wmbus_version"] = wc["wmbus_version"]
        tech_config["wmbus_device_type"] = wc.get("wmbus_device_type")
        tech_config["data_record_mapping"] = wc.get("data_record_mapping", [])
        tech_config["encryption_required"] = wc.get("encryption_required", False)
        if wc.get("shared_encryption_key"):
            tech_config["shared_encryption_key"] = wc["shared_encryption_key"]
        if wc.get("wmbusmeters_driver"):
            tech_config["wmbusmeters_driver"] = wc["wmbusmeters_driver"]
        if wc.get("field_map"):
            tech_config["field_map"] = wc["field_map"]
        if wc.get("is_mvt_default"):
            tech_config["is_mvt_default"] = wc["is_mvt_default"]

    device = {
        "key": snapshot.get("key", ""),
        "vendor_name": snapshot.get("vendor", ""),
        "model_number": snapshot.get("model_number", ""),
        "name": snapshot.get("name", ""),
        "device_type": snapshot.get("device_type", ""),
        "description": snapshot.get("description", ""),
        "technology_config": tech_config,
    }

    ctrl = snapshot.get("control_config", {})
    if ctrl and (ctrl.get("controllable") or ctrl.get("capabilities")):
        device["control_config"] = ctrl

    proc = snapshot.get("processor_config", {})
    if proc and proc.get("decoder_type"):
        device["processor_config"] = proc

    return device
