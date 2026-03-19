"""YAML import logic for device definitions."""

import logging
from pathlib import Path

import yaml
from django.utils.text import slugify

from .history import record_history, snapshot_device
from .models import (
    ControlConfig,
    DeviceHistory,
    LoRaWANConfig,
    ModbusConfig,
    ProcessorConfig,
    RegisterDefinition,
    Vendor,
    VendorModel,
    WMBusConfig,
)

logger = logging.getLogger(__name__)


def import_from_yaml(devices_path: str | Path, manifest_path: str | Path, clear: bool = False) -> dict:
    """Import device definitions from YAML files.

    Returns a dict with import statistics.
    """
    devices_path = Path(devices_path)
    manifest_path = Path(manifest_path)

    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {manifest_path}")
    if not devices_path.exists():
        raise FileNotFoundError(f"Devices directory not found: {devices_path}")

    with open(manifest_path) as f:
        manifest = yaml.safe_load(f)

    stats = {
        "vendors_created": 0,
        "vendors_updated": 0,
        "devices_created": 0,
        "devices_updated": 0,
        "errors": [],
    }

    if clear:
        VendorModel.objects.all().delete()
        Vendor.objects.all().delete()
        logger.info("Cleared existing vendors and devices")

    for vendor_entry in manifest.get("vendors", []):
        vendor_name = vendor_entry["name"]
        vendor_file = vendor_entry["file"]
        file_path = devices_path / vendor_file

        if not file_path.exists():
            stats["errors"].append(f"File not found: {file_path}")
            logger.warning("File not found: %s", file_path)
            continue

        vendor, created = Vendor.objects.get_or_create(
            slug=slugify(vendor_name),
            defaults={"name": vendor_name},
        )
        if created:
            stats["vendors_created"] += 1
            logger.info("Created vendor: %s", vendor_name)
        else:
            stats["vendors_updated"] += 1

        with open(file_path) as f:
            data = yaml.safe_load(f)

        devices_key = "models" if "models" in (data or {}) else "device_types"
        if not data or devices_key not in data:
            logger.warning("No devices in %s", file_path)
            continue

        for device_data in data[devices_key]:
            try:
                _import_device(vendor, device_data, stats)
            except Exception as e:
                error_msg = f"Error importing {device_data.get('model_number', '?')} from {vendor_name}: {e}"
                stats["errors"].append(error_msg)
                logger.error(error_msg)

    return stats


def _import_device(vendor: Vendor, data: dict, stats: dict) -> VendorModel:
    """Import a single device type from YAML data."""
    tech_config = data.get("technology_config", {})
    technology = tech_config.get("technology", "")

    # Check if device already exists so we can capture a pre-update snapshot
    existing = VendorModel.objects.filter(vendor=vendor, model_number=data["model_number"]).first()
    old_snapshot = snapshot_device(existing) if existing else None

    device, created = VendorModel.objects.update_or_create(
        vendor=vendor,
        model_number=data["model_number"],
        defaults={
            "name": data.get("name", ""),
            "device_type": data.get("device_type", ""),
            "technology": technology,
            "description": data.get("description", "") or "",
        },
    )

    if created:
        stats["devices_created"] += 1
        logger.info("Created device: %s", device)
    else:
        stats["devices_updated"] += 1
        logger.info("Updated device: %s", device)

    # Import technology-specific config
    if technology == "modbus":
        _import_modbus_config(device, tech_config)
    elif technology == "lorawan":
        _import_lorawan_config(device, tech_config)
    elif technology == "wmbus":
        _import_wmbus_config(device, tech_config)

    # Import control config (only if meaningful data present)
    control_data = data.get("control_config", {})
    if control_data and (control_data.get("controllable") or control_data.get("capabilities")):
        ControlConfig.objects.update_or_create(
            device_type=device,
            defaults={
                "controllable": control_data.get("controllable", False),
                "capabilities": control_data.get("capabilities", {}),
            },
        )

    # Import processor config (only if meaningful data present)
    processor_data = data.get("processor_config", {})
    if processor_data and processor_data.get("decoder_type"):
        ProcessorConfig.objects.update_or_create(
            device_type=device,
            defaults={
                "decoder_type": processor_data.get("decoder_type", ""),
            },
        )

    # Record device history
    if created:
        record_history(device, DeviceHistory.Action.CREATED, user=None)
    else:
        record_history(device, DeviceHistory.Action.UPDATED, user=None, previous_snapshot=old_snapshot)

    return device


def _import_modbus_config(device: VendorModel, tech_config: dict):
    """Import Modbus-specific configuration."""
    modbus_config, _ = ModbusConfig.objects.update_or_create(
        device_type=device,
        defaults={
            "function": tech_config.get("function", ""),
            "byte_order": tech_config.get("byte_order", ""),
            "word_order": tech_config.get("word_order", ""),
        },
    )

    # Clear existing registers and re-import
    modbus_config.register_definitions.all().delete()

    for reg_data in tech_config.get("register_definitions", []):
        field = reg_data.get("field", {})
        RegisterDefinition.objects.create(
            modbus_config=modbus_config,
            field_name=field.get("name", ""),
            field_unit=field.get("unit", "") or "",
            address=reg_data.get("address", 0),
            data_type=reg_data.get("data_type", "uint16"),
            scale=reg_data.get("scale", 1.0),
            offset=reg_data.get("offset", 0.0),
        )


def _import_lorawan_config(device: VendorModel, tech_config: dict):
    """Import LoRaWAN-specific configuration."""
    LoRaWANConfig.objects.update_or_create(
        device_type=device,
        defaults={
            "device_class": tech_config.get("device_class", ""),
            "downlink_f_port": tech_config.get("downlink_f_port"),
            "payload_codec": tech_config.get("payload_codec", {}),
            "field_map": tech_config.get("field_map", {}),
        },
    )


def _import_wmbus_config(device: VendorModel, tech_config: dict):
    """Import wM-Bus-specific configuration."""
    obj, _ = WMBusConfig.objects.update_or_create(
        device_type=device,
        defaults={
            "manufacturer_code": tech_config.get("manufacturer_code", ""),
            "wmbus_version": tech_config.get("wmbus_version", ""),
            "wmbus_device_type": tech_config.get("wmbus_device_type"),
            "data_record_mapping": tech_config.get("data_record_mapping", []),
            "encryption_required": tech_config.get("encryption_required", False),
            "shared_encryption_key": tech_config.get("shared_encryption_key", ""),
            "wmbusmeters_driver": tech_config.get("wmbusmeters_driver", ""),
            "field_map": tech_config.get("field_map", {}),
            "is_mvt_default": tech_config.get("is_mvt_default", False),
        },
    )
    obj.full_clean()
