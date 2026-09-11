"""Build the published content document of a library version.

One builder for every consumer: the ``/api/v1/library/content/<v>/`` endpoint
that Spark instances sync from, and the UI download used to carry the same
document to air-gapped (on-prem) instances as a file. Both must produce a
byte-identical shape, otherwise ``sync_device_library --from-file`` drifts
from the online sync.
"""

from library.assets import EMPTY_ASSETS, assets_payload
from library.exporters import effective_field_mappings_from_config, snapshot_to_schema
from library.models import (
    DeviceHistory,
    DeviceType,
    DeviceTypeHistory,
    LibraryVersion,
    LibraryVersionDevice,
    LibraryVersionDeviceType,
    LibraryVersionMetric,
    Metric,
    MetricHistory,
    VendorModel,
)

from .serializers import DeviceTypeSerializer, MetricSerializer


def parse_technologies(raw: str) -> set[str]:
    """``"wmbus, modbus"`` → ``{"wmbus", "modbus"}``; empty string → empty set (no filter)."""
    return {t.strip() for t in (raw or "").split(",") if t.strip()}


def build_version_content(lib_version: LibraryVersion, technologies: set[str] | None = None) -> dict:
    """Return ``{version, schema_version, metrics, device_types, vendors}`` pinned
    to the state at publish time. ``technologies`` narrows ``vendors`` to models of
    those technologies (constrained clients, single-technology instances); the
    L1/L2 catalogues are always complete."""
    technologies = technologies or set()

    entries = lib_version.device_changes.exclude(
        change_type=LibraryVersionDevice.ChangeType.REMOVED,
    )

    history_lookup = {}
    for entry in entries:
        if entry.device_type_id:
            snapshot = (
                DeviceHistory.objects.filter(
                    device_id=entry.device_type_id,
                    version=entry.device_version,
                )
                .values_list("snapshot", flat=True)
                .first()
            )
            if snapshot:
                history_lookup[entry.device_type_id] = snapshot

    # Documentation assets are not versioned content: the file itself is
    # fetched live, so the metadata reflects the current state too. Models
    # deleted since the publish carry an empty block.
    assets_by_key = {
        str(m.key): assets_payload(m)
        for m in VendorModel.objects.filter(
            pk__in=[e.device_type_id for e in entries if e.device_type_id],
        ).prefetch_related("documents").select_related("image", "procedure")
    }

    vendors: dict[str, dict] = {}
    for entry in entries:
        snap = history_lookup.get(entry.device_type_id)
        if not snap:
            continue
        if technologies and snap.get("technology") not in technologies:
            continue
        vendor_name = snap.get("vendor", "Unknown")
        vendor_key = snap.get("vendor_key", "")
        if vendor_name not in vendors:
            vendors[vendor_name] = {"key": vendor_key, "models": []}
        model_schema = snapshot_to_schema(snap)
        proc = model_schema.get("processor_config")
        if proc:
            # Publish the merged field+extra list so instances ingest both
            # (consumers read ``effective_field_mappings`` and fall back to
            # ``field_mappings``; extra mappings would otherwise be dropped).
            model_schema["effective_field_mappings"] = effective_field_mappings_from_config(proc)
        model_schema["assets"] = assets_by_key.get(snap.get("key"), EMPTY_ASSETS)
        vendors[vendor_name]["models"].append(model_schema)

    vendor_list = [
        {"key": info["key"], "name": name, "models": info["models"]}
        for name, info in sorted(vendors.items())
    ]

    return {
        "version": lib_version.version,
        "schema_version": lib_version.schema_version,
        "metrics": _resolve_metric_snapshots(lib_version),
        "device_types": _resolve_device_type_snapshots(lib_version),
        "vendors": vendor_list,
    }


def _resolve_metric_snapshots(lib_version: LibraryVersion) -> list:
    """L1 Metric snapshots pinned to this version (same shape as
    ``MetricSerializer``). ``REMOVED`` entries are skipped. Versions published
    before migration 0035 have no manifest rows and fall back to current state."""
    entries = lib_version.metric_changes.exclude(
        change_type=LibraryVersionMetric.ChangeType.REMOVED,
    )
    if not entries.exists():
        return MetricSerializer(Metric.objects.all(), many=True).data

    out = []
    for entry in entries:
        if not entry.metric_id:
            continue
        snap = (
            MetricHistory.objects.filter(
                metric_id=entry.metric_id,
                version=entry.metric_version,
            )
            .values_list("snapshot", flat=True)
            .first()
        )
        if snap:
            out.append(snap)
    return out


def _resolve_device_type_snapshots(lib_version: LibraryVersion) -> list:
    """L2 sibling of ``_resolve_metric_snapshots``."""
    entries = lib_version.device_type_changes.exclude(
        change_type=LibraryVersionDeviceType.ChangeType.REMOVED,
    )
    if not entries.exists():
        return DeviceTypeSerializer(DeviceType.objects.all(), many=True).data

    out = []
    for entry in entries:
        if not entry.device_type_id:
            continue
        snap = (
            DeviceTypeHistory.objects.filter(
                device_type_id=entry.device_type_id,
                version=entry.device_type_version,
            )
            .values_list("snapshot", flat=True)
            .first()
        )
        if snap:
            out.append(snap)
    return out
