"""YAML import logic for device definitions."""

import logging
from pathlib import Path

import yaml
from django.utils.text import slugify

from .history import record_history, snapshot_device
from .models import (
    ControlConfig,
    DeviceHistory,
    DeviceType,
    LoRaWANConfig,
    Metric,
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
        "device_types_created": 0,
        "device_types_updated": 0,
        "errors": [],
    }

    if clear:
        VendorModel.objects.all().delete()
        Vendor.objects.all().delete()
        logger.info("Cleared existing vendors and devices")

    # Schema-v4: import the L1 Metric catalogue first (vocabulary of metrics
    # referenced by every L4 mapping). Then L2 device_types, then vendors +
    # models. Older manifests (v3 / v2) just lack the metrics block; legacy
    # ``target`` strings on entries are auto-promoted to Metric rows below
    # (tolerant migration).
    for m_data in manifest.get("metrics", []) or []:
        try:
            _import_metric(m_data)
        except Exception as e:
            stats["errors"].append(f"Error importing metric {m_data.get('key', '?')}: {e}")
            logger.error("Error importing metric %s: %s", m_data.get("key"), e)

    # Import top-level device_types section so VendorModel imports below can
    # resolve device_type_fk by key/code. Older manifests without the section
    # rely on the seeded defaults from the migration.
    for dt_data in manifest.get("device_types", []) or []:
        try:
            _import_device_type(dt_data, stats)
        except Exception as e:
            error_msg = f"Error importing device_type {dt_data.get('code', '?')}: {e}"
            stats["errors"].append(error_msg)
            logger.error(error_msg)

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


def _import_metric(data: dict) -> Metric:
    """Upsert an L1 Metric row from YAML."""
    key = (data.get("key") or "").strip()
    if not key:
        raise ValueError("metric entry is missing 'key'")
    defaults = {
        "label": data.get("label") or key.split(":", 1)[-1].replace("_", " ").title(),
        "unit": data.get("unit", "") or "",
        "data_type": data.get("data_type", "decimal"),
        "description": data.get("description", "") or "",
    }
    obj, _ = Metric.objects.update_or_create(key=key, defaults=defaults)
    return obj


def _convert_legacy_field_mappings(base: list[dict], extras: list[dict]) -> list[dict]:
    """Translate schema-v3 ProcessorConfig mappings into the v4 single-slot shape.

    - Concatenates ``base`` + ``extras`` (extras win on same-source collision,
      preserving the historical effective-list order).
    - Keeps per-entry ``target`` (now points at an L1 Metric.key).
    - Drops per-entry ``unit`` (resolved from L1) and ``primary`` (resolved
      from L2).
    - Drops per-entry ``transform`` — production data only carried type
      coercion values like ``to_float`` which the new model doesn't track.
      Unit conversion is now expressed via ``scale``/``offset``.
    - Auto-creates missing L1 Metric rows so downstream lookups don't fail.
    """
    if extras:
        extra_sources = {e.get("source") for e in extras if e.get("source")}
        merged = [m for m in base if m.get("source") not in extra_sources] + list(extras)
    else:
        merged = list(base)

    out: list[dict] = []
    for entry in merged:
        target = entry.get("target") or entry.get("metric")
        if not target:
            continue
        new_entry = {"source": entry.get("source"), "target": target}
        Metric.objects.get_or_create(
            key=target,
            defaults={
                "label": target.split(":", 1)[-1].replace("_", " ").title(),
                "unit": entry.get("unit", "") or "",
                "data_type": "decimal",
            },
        )
        if entry.get("scale") not in (None, 1):
            new_entry["scale"] = entry["scale"]
        if entry.get("offset") not in (None, 0):
            new_entry["offset"] = entry["offset"]
        if entry.get("tags"):
            new_entry["tags"] = entry["tags"]
        out.append(new_entry)
    return out


def _convert_legacy_default_field_mappings(legacy: list[dict]) -> list[dict]:
    """Translate schema-v3 ``default_field_mappings`` entries to v4 ``metrics``.

    Old shape: ``[{source, target, transform?, primary?}]``
    New shape: ``[{metric, tier}]``
    Source/transform are dropped (they were decoder concerns that don't
    belong on the type). ``primary`` flag promotes to tier=primary,
    otherwise tier=secondary.
    """
    seen = set()
    out: list[dict] = []
    for entry in legacy or []:
        target = entry.get("target")
        if not target or target in seen:
            continue
        seen.add(target)
        tier = "primary" if entry.get("primary") else "secondary"
        out.append({"metric": target, "tier": tier})
    return out


def _import_device_type(data: dict, stats: dict) -> DeviceType:
    code = data.get("code", "").strip()
    if not code:
        raise ValueError("device_type entry is missing 'code'")

    # Schema-v4 carries ``metrics`` directly; legacy v3 manifests still ship
    # ``default_field_mappings`` and we translate on the fly.
    if "metrics" in data:
        metrics = data.get("metrics") or []
    else:
        metrics = _convert_legacy_default_field_mappings(
            data.get("default_field_mappings") or [],
        )
    # Auto-create any L1 Metric rows referenced from the profile but missing
    # from the catalogue (tolerant import; operator tidies in admin).
    for entry in metrics:
        metric_key = entry.get("metric")
        if metric_key:
            Metric.objects.get_or_create(
                key=metric_key,
                defaults={
                    "label": metric_key.split(":", 1)[-1].replace("_", " ").title(),
                    "data_type": "decimal",
                },
            )

    defaults = {
        "label": data.get("label", code.replace("_", " ").title()),
        "description": data.get("description", "") or "",
        "icon": data.get("icon", "") or "",
        "metrics": metrics,
    }
    if data.get("key"):
        defaults["key"] = data["key"]

    obj, created = DeviceType.objects.update_or_create(code=code, defaults=defaults)
    stats["device_types_created" if created else "device_types_updated"] += 1
    logger.info("%s device_type %s", "Created" if created else "Updated", code)
    return obj


def _resolve_device_type_fk(data: dict) -> DeviceType | None:
    """Look up the DeviceType row referenced by a VendorModel YAML entry.

    Prefers ``device_type_key`` (UUID — direct identity); falls back to
    matching the legacy ``device_type`` enum string against ``DeviceType.code``.
    Returns ``None`` when no match is found; the FK column then stays null
    until an operator wires it up manually.
    """
    key = data.get("device_type_key")
    if key:
        match = DeviceType.objects.filter(key=key).first()
        if match:
            return match

    code = data.get("device_type", "").strip()
    if code:
        match = DeviceType.objects.filter(code=code).first()
        if match:
            return match

    return None


def _import_device(vendor: Vendor, data: dict, stats: dict) -> VendorModel:
    """Import a single device type from YAML data."""
    tech_config = data.get("technology_config", {})
    technology = tech_config.get("technology", "")
    device_type_fk = _resolve_device_type_fk(data)

    # Check if device already exists so we can capture a pre-update snapshot
    existing = VendorModel.objects.filter(vendor=vendor, model_number=data["model_number"]).first()
    old_snapshot = snapshot_device(existing) if existing else None

    device, created = VendorModel.objects.update_or_create(
        vendor=vendor,
        model_number=data["model_number"],
        defaults={
            "name": data.get("name", ""),
            "device_type": data.get("device_type", ""),
            "device_type_fk": device_type_fk,
            "technology": technology,
            "description": data.get("description", "") or "",
            # Per-meter knob — absent in YAML means "no per-meter override".
            "offline_window_seconds": data.get("offline_window_seconds"),
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

    # Import processor config (only if meaningful data present). Schema-v3
    # had two slots (``field_mappings`` replace + ``extra_field_mappings``
    # additive) and each entry carried ``target`` + ``unit`` + ``primary``.
    # Schema-v4 collapses to one slot and entries use ``metric`` (no unit,
    # no primary). Translate both shapes here.
    processor_data = data.get("processor_config", {})
    if processor_data and (
        processor_data.get("decoder_type")
        or processor_data.get("field_mappings")
        or processor_data.get("extra_field_mappings")
        or processor_data.get("extra_config")
    ):
        ProcessorConfig.objects.update_or_create(
            device_type=device,
            defaults={
                "decoder_type": processor_data.get("decoder_type", ""),
                "extra_config": processor_data.get("extra_config", {}),
                "field_mappings": _convert_legacy_field_mappings(
                    processor_data.get("field_mappings") or [],
                    processor_data.get("extra_field_mappings") or [],
                ),
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
    # payload_codec can be a structured dict {format, script} or a plain string (legacy)
    raw_codec = tech_config.get("payload_codec", "")
    if isinstance(raw_codec, dict):
        codec_format = raw_codec.get("format", "ttn_v3")
        codec_script = raw_codec.get("script", "")
    else:
        codec_format = "ttn_v3"
        codec_script = str(raw_codec) if raw_codec else ""

    LoRaWANConfig.objects.update_or_create(
        device_type=device,
        defaults={
            "device_class": tech_config.get("device_class", ""),
            "downlink_f_port": tech_config.get("downlink_f_port"),
            "codec_format": codec_format,
            "payload_codec": codec_script,
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
