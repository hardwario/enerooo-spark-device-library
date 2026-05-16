# Versioning parity for L1 Metric + L2 DeviceType

Before this change, `VendorModel` was the only versioned entity in the library — `DeviceHistory` snapshots per change, `LibraryVersionDevice` pins the snapshot version to each published `LibraryVersion`. `Metric` and `DeviceType` carried only `created` / `modified` timestamps. The `LibraryContentViewSet` consequently served the *current* state of L1 + L2 regardless of which library version a Spark gateway asked for — operators editing a metric's bounds would retroactively rewrite every historical version.

This document describes the schema-v5 extension that closes the gap.

## What changed

Two new history tables (parallel to `DeviceHistory`):

| Model | Tracks | Mirrors |
|---|---|---|
| `MetricHistory`     | Per-row snapshots of every `Metric` change   | `DeviceHistory` |
| `DeviceTypeHistory` | Per-row snapshots of every `DeviceType` change | `DeviceHistory` |

Two new link tables (parallel to `LibraryVersionDevice`):

| Model | Pins a Metric/DeviceType to a published LibraryVersion |
|---|---|
| `LibraryVersionMetric`     | `(library_version, metric, metric_version, change_type)`           |
| `LibraryVersionDeviceType` | `(library_version, device_type, device_type_version, change_type)` |

Both link tables expose the same `ChangeType` enum (`added` / `modified` / `removed` / `unchanged`) that `LibraryVersionDevice` already uses.

## Where history gets recorded

| Trigger | Hook |
|---|---|
| `MetricCreateView` form_valid       | `record_metric_history(..., CREATED)` |
| `MetricUpdateView` form_valid       | `record_metric_history(..., UPDATED, previous_snapshot=…)` |
| `MetricDeleteView` post             | `record_metric_history(..., DELETED, previous_snapshot=…)` then `metric.delete()` |
| `DeviceTypeCreateView` form_valid   | `record_device_type_history(..., CREATED)` |
| `DeviceTypeUpdateView` form_valid   | `record_device_type_history(..., UPDATED, previous_snapshot=…)` |
| `DeviceTypeDeleteView` post         | `record_device_type_history(..., DELETED, previous_snapshot=…)` then `dt.delete()` |
| `_import_metric` (YAML import)      | `record_metric_history(..., CREATED or UPDATED)` based on diff |
| `_import_device_type` (YAML import) | `record_device_type_history(..., CREATED or UPDATED)` based on diff |
| `VersionCreateView` post (publish)  | Backfills missing history entries before iterating, so any row touched without a hook still ends up pinned |

The history-on-delete pattern preserves an audit trail even though `metric` / `device_type` FKs on the history rows are `SET_NULL` — the `metric_key` / `device_type_code` columns keep the original key as a grep-able label.

## How publish populates the manifests

`VersionCreateView.post` does three things in sequence:

1. **Backfill missing history.** Any `VendorModel` / `Metric` / `DeviceType` without history rows (e.g. auto-created rows from `ProcessorConfig.save()`) gets a v1 `CREATED` snapshot first.
2. **Iterate current rows and write manifest entries.** For each entity, look up its latest `*History.version`, compare against the previous published version's manifest, and write a `Library­Version*` row with the appropriate `change_type`.
3. **Detect removals.** Anything in the previous manifest but not in current state gets a `REMOVED` manifest entry with the last known version.

The per-entity logic is factored into `VersionCreateView._publish_entities()` so the L1 and L2 blocks don't duplicate the ~30 lines of compare-and-write boilerplate that the VendorModel block needs.

## How content endpoint resolves snapshots

`LibraryContentViewSet.retrieve(version=N)` previously did:

```python
"metrics": MetricSerializer(Metric.objects.all(), many=True).data,
"device_types": DeviceTypeSerializer(DeviceType.objects.all(), many=True).data,
```

— current state regardless of which `N` was requested. Now:

```python
"metrics": self._resolve_metric_snapshots(lib_version),
"device_types": self._resolve_device_type_snapshots(lib_version),
```

Each helper:

1. Iterates the version's `metric_changes` / `device_type_changes`, excluding `REMOVED` entries.
2. For each entry, fetches the matching `MetricHistory` / `DeviceTypeHistory` snapshot by `(entity_id, version)`.
3. Returns the list of snapshot dicts — same shape as the serializer would have produced from current state.

### Fallback for pre-0035 library versions

`LibraryVersion` rows published *before* this migration have no `metric_changes` / `device_type_changes` entries. The helpers detect the empty queryset and fall back to serving current state via `MetricSerializer(Metric.objects.all(), …)` / `DeviceTypeSerializer(DeviceType.objects.all(), …)`. This keeps content retrieval for legacy versions working (best-effort current state) without requiring a one-shot backfill of every historical `LibraryVersion`.

Operators who want pre-0035 versions properly pinned can simply bump-publish a new version; from that point forward the snapshots are correct.

## Backfill in migration 0035

Migration `0035_metric_devicetype_versioning` creates the four tables and runs a `RunPython` step that:

- Creates a v1 `CREATED` `MetricHistory` for every existing `Metric` row that doesn't have one yet
- Creates a v1 `CREATED` `DeviceTypeHistory` for every existing `DeviceType` row that doesn't have one yet
- Idempotent — second run is a no-op

This ensures `LibraryContentViewSet.retrieve()` can resolve snapshots for every entity going forward, without forcing every operator to re-publish.

## What's still owned by current state (and why)

| Concern | Where it lives | Why not versioned |
|---|---|---|
| `Vendor` (name/slug)              | Live row only | Vendor identity is a label; renames are rare and operationally always *now*. |
| `LibraryVersion` itself           | Live row only | Versions are the audit unit — versioning them would be turtles. |
| `GatewayAssignment`               | Live row only | Operational data, not part of library content. |
| `APIKey`                          | Live row only | Operational data. |

The set of versioned entities matches what the published library promises to be stable for — schema (L1), profiles (L2), and device definitions (L4).

## Test coverage

`src/library/tests/test_versioning_parity.py` covers:

- **Backfill**: every existing Metric and DeviceType has a v1 history entry post-migration, with the right `kind` + bounds + aggregation fields preserved.
- **Record helpers**: `record_metric_history` and `record_device_type_history` bump versions correctly and compute diffs against the previous snapshot.
- **Publish flow**: first publish marks every entity `ADDED`; mutating an entity between two publishes marks it `MODIFIED` on the second; unchanged entities are `UNCHANGED`.
- **Content endpoint roundtrip**: editing a metric label, publishing v2, then requesting `/api/v1/library/content/<v1>/` still returns the *original* label — confirming snapshots aren't mutated by current-state changes.
- **Pre-0035 fallback**: a synthetic LibraryVersion without manifest entries falls back to current state without crashing.

11 tests total — `pytest library/tests/test_versioning_parity.py`.
