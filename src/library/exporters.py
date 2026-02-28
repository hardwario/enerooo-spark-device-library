"""YAML export logic for device definitions."""

import logging
from pathlib import Path

import yaml

from .models import DeviceType, Vendor

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
    }

    manifest_vendors = []

    for vendor in Vendor.objects.prefetch_related("device_types").all():
        devices = vendor.device_types.all()
        if not devices.exists():
            continue

        device_types = []
        for device in devices:
            device_types.append(_export_device(device))

        vendor_data = {"device_types": device_types}

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

    # Export manifest
    from .models import LibraryVersion

    current_version = LibraryVersion.objects.filter(is_current=True).first()
    manifest = {
        "version": current_version.version if current_version else "0.0.0",
        "schema_version": current_version.schema_version if current_version else 2,
        "vendors": manifest_vendors,
    }

    manifest_path = output_dir.parent / "manifest.yaml"
    with open(manifest_path, "w") as f:
        yaml.dump(manifest, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return stats


def _export_device(device: DeviceType) -> dict:
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
    return data


def _export_tech_config(device: DeviceType) -> dict:
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
        except DeviceType.modbus_config.RelatedObjectDoesNotExist:
            pass

    elif device.technology == "lorawan":
        try:
            lorawan = device.lorawan_config
            if lorawan.device_class:
                config["device_class"] = lorawan.device_class
            if lorawan.downlink_f_port is not None:
                config["downlink_f_port"] = lorawan.downlink_f_port
        except DeviceType.lorawan_config.RelatedObjectDoesNotExist:
            pass

    elif device.technology == "wmbus":
        try:
            wmbus = device.wmbus_config
            config["manufacturer_code"] = wmbus.manufacturer_code
            config["wmbus_device_type"] = wmbus.wmbus_device_type
            config["data_record_mapping"] = wmbus.data_record_mapping
            config["encryption_required"] = wmbus.encryption_required
            if wmbus.shared_encryption_key:
                config["shared_encryption_key"] = wmbus.shared_encryption_key
        except DeviceType.wmbus_config.RelatedObjectDoesNotExist:
            pass

    return config


def _export_control_config(device: DeviceType) -> dict:
    """Export control config."""
    try:
        ctrl = device.control_config
        return {
            "capabilities": ctrl.capabilities,
            "controllable": ctrl.controllable,
        }
    except DeviceType.control_config.RelatedObjectDoesNotExist:
        return {}


def _export_processor_config(device: DeviceType) -> dict:
    """Export processor config."""
    try:
        proc = device.processor_config
        if proc.decoder_type:
            return {"decoder_type": proc.decoder_type}
    except DeviceType.processor_config.RelatedObjectDoesNotExist:
        pass
    return {}
