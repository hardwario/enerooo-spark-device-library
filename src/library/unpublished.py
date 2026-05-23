"""Detect entities modified since the current LibraryVersion was published.

Spark instances pull device definitions through the sync API, which
serves the snapshot pinned by the current LibraryVersion's manifest.
An edit saved in the UI does *not* reach those clients until an
operator clicks Publish — at which point a new LibraryVersion row is
created and its manifest re-pins to the latest per-entity history
versions. Until then the edit is invisible to consumers.

This module computes, per entity type (VendorModel / Metric /
DeviceType), the rows whose latest history version diverges from the
version pinned by the current LibraryVersion — plus rows added since
the last publish and rows pinned by the manifest but no longer in the
database (unpublished removals). The result feeds the global banner
(via the context processor) and the /versions/ landing page.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from django.db.models import Max

from .models import (
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


@dataclass
class UnpublishedEntity:
    pk: str
    label: str
    change_type: str  # "added" | "modified" | "removed"
    detail_url_name: str | None  # None for removed (entity no longer exists)


@dataclass
class UnpublishedChangesSummary:
    current_version: int | None
    next_version: int
    models: list[UnpublishedEntity] = field(default_factory=list)
    metrics: list[UnpublishedEntity] = field(default_factory=list)
    device_types: list[UnpublishedEntity] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.models) + len(self.metrics) + len(self.device_types)

    def as_template_context(self) -> dict[str, Any]:
        return {
            "current_version": self.current_version,
            "next_version": self.next_version,
            "total": self.total,
            "models": self.models,
            "metrics": self.metrics,
            "device_types": self.device_types,
            "models_count": len(self.models),
            "metrics_count": len(self.metrics),
            "device_types_count": len(self.device_types),
        }


def _detect(
    entity_qs,
    history_model,
    link_model,
    *,
    current_version: LibraryVersion | None,
    label_fn: Callable[[Any], str],
    history_fk: str,
    link_fk: str,
    link_version_attr: str,
    link_label_field: str,
    link_relation: str,
    detail_url_name: str,
) -> list[UnpublishedEntity]:
    """Walk one entity type and emit added/modified/removed rows.

    Deletion is detected via FK nullification: every link row's FK
    uses ``on_delete=SET_NULL``, so a manifest entry that wasn't
    REMOVED at publish time but whose FK is now null can only mean
    the underlying entity was deleted after publish.
    """
    pinned: dict[Any, int] = {}
    orphaned_labels: list[str] = []
    if current_version is not None:
        rows = getattr(current_version, link_relation).exclude(
            change_type=link_model.ChangeType.REMOVED,
        )
        for row in rows:
            fk_id = getattr(row, f"{link_fk}_id")
            if fk_id:
                pinned[fk_id] = getattr(row, link_version_attr)
            else:
                orphaned_labels.append(getattr(row, link_label_field))

    latest_versions: dict[Any, int] = dict(
        history_model.objects.values(history_fk).annotate(v=Max("version")).values_list(history_fk, "v"),
    )

    results: list[UnpublishedEntity] = []
    for ent in entity_qs:
        latest = latest_versions.get(ent.pk)
        pinned_v = pinned.get(ent.pk)

        if pinned_v is None:
            # Not in the manifest → added since the last publish (or no
            # publish has happened yet, in which case every row qualifies).
            results.append(
                UnpublishedEntity(
                    pk=str(ent.pk),
                    label=label_fn(ent),
                    change_type="added",
                    detail_url_name=detail_url_name,
                )
            )
        elif latest is not None and latest > pinned_v:
            results.append(
                UnpublishedEntity(
                    pk=str(ent.pk),
                    label=label_fn(ent),
                    change_type="modified",
                    detail_url_name=detail_url_name,
                )
            )

    for label in orphaned_labels:
        results.append(
            UnpublishedEntity(
                pk="",
                label=label,
                change_type="removed",
                detail_url_name=None,
            )
        )

    results.sort(key=lambda e: (e.change_type, e.label.lower()))
    return results


def unpublished_changes_summary() -> UnpublishedChangesSummary:
    """Return entities whose state diverges from the current LibraryVersion.

    A non-zero ``total`` means at least one entity has been edited,
    created, or deleted since the last publish — Spark instances won't
    see those edits until the operator publishes a new LibraryVersion.
    """
    current = LibraryVersion.objects.filter(is_current=True).first()
    next_version = (current.version + 1) if current else 1

    models = _detect(
        VendorModel.objects.select_related("vendor").all(),
        DeviceHistory,
        LibraryVersionDevice,
        current_version=current,
        label_fn=lambda v: str(v),
        history_fk="device",
        link_fk="device_type",
        link_version_attr="device_version",
        link_label_field="device_label",
        link_relation="device_changes",
        detail_url_name="library:model-detail",
    )
    metrics = _detect(
        Metric.objects.all(),
        MetricHistory,
        LibraryVersionMetric,
        current_version=current,
        label_fn=lambda m: m.key,
        history_fk="metric",
        link_fk="metric",
        link_version_attr="metric_version",
        link_label_field="metric_key",
        link_relation="metric_changes",
        detail_url_name="library:metric-detail",
    )
    device_types = _detect(
        DeviceType.objects.all(),
        DeviceTypeHistory,
        LibraryVersionDeviceType,
        current_version=current,
        label_fn=lambda dt: dt.code,
        history_fk="device_type",
        link_fk="device_type",
        link_version_attr="device_type_version",
        link_label_field="device_type_code",
        link_relation="device_type_changes",
        detail_url_name="library:devicetype-detail",
    )

    return UnpublishedChangesSummary(
        current_version=current.version if current else None,
        next_version=next_version,
        models=models,
        metrics=metrics,
        device_types=device_types,
    )
