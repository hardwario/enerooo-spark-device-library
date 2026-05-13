# Metric mapping architecture

Four layers, split by responsibility. L3 and L4 already exist implicitly; L1 and L2 are new.

| Layer | What | Where |
|---|---|---|
| **L1 Metric** | Global catalogue of metrics (label, unit, data_type) | Platform |
| **L2 DeviceType profile** | Which metrics this device type tracks + tier | Per type |
| **L3 Decoder** | Bytes → named dict | Per model (Modbus / wM-Bus / LoRaWAN) |
| **L4 Mapping** | Decoded field → target metric, optional `scale` + `offset` | Per model |

L4 entries use the key name **`target`** for the pointer at an L1 `Metric.key` — kept so existing decoders (Spark) reading `entry["target"]` keep working without code change. L2 entries use **`metric`** because they're a declaration (this type tracks this metric), not a decoder mapping.

**Multi-channel devices** (3-phase meters, multi-tariff, …) model each channel as a separate L1 metric (`elec:voltage_l1` / `elec:voltage_l2` / `elec:voltage_l3`) — no parallel "tags" concept. Catalogue grows by N entries; data model stays flat. Auto-create on save handles the L1 row creation.

**Decoder type auto-derive.** `ProcessorConfig.decoder_type` is filled by the model's `save()` based on `VendorModel.technology`: wmbus → `wmbus_field_map`, lorawan → `js_codec` (if a payload codec is set) or `lorawan_field_map`. Operator only sets it explicitly for edge cases.

L3 emits canonical units wherever we own the decoder config (Modbus `scale`/`offset`, wmbusmeters driver). For vendor LoRaWAN codecs we pull from upstream and don't fork, L4 carries `scale` (default 1) and `offset` (default 0) for a generic linear conversion `value * scale + offset` — covers Wh→kWh, dWh→kWh, °F→°C, %→ratio without enumerating each.

Model entries referencing a target key not yet in the L1 catalogue **auto-create** the row on save (tolerant pattern — operator tidies label/unit in admin afterwards). Lets vendors land custom metrics like `temp:temperature_boiler` without blocking on catalogue maintenance.

---

## L1 — Metric Catalogue

```yaml
- {key: heat:total_energy,  label: "Total Energy",  unit: kWh,   data_type: decimal,
   min_value: 0, max_value: 1e12, monotonic: true}
- {key: heat:total_volume,  label: "Total Volume",  unit: m³,    data_type: decimal,
   min_value: 0, max_value: 1e9,  monotonic: true}
- {key: elec:voltage,       label: "Voltage",       unit: V,     data_type: decimal,
   min_value: 0, max_value: 1000}
- {key: env:temperature,    label: "Temperature",   unit: °C,    data_type: decimal,
   min_value: -100, max_value: 150}
- {key: device:battery,     label: "Battery",       unit: ratio, data_type: decimal,
   min_value: 0, max_value: 1}
- {key: device:rssi,        label: "Signal",        unit: dBm,   data_type: integer,
   min_value: -150, max_value: 0}
- {key: device:status,      label: "Status",        unit: "",    data_type: enum}
```

The `key` namespace prefix is semantic: `heat:total_energy` (calorific) ≠ `elec:total_energy` (electrical), same unit but different physical quantity. The `device:` namespace covers cross-domain health telemetry (battery, RSSI, firmware, status) regardless of underlying technology — no separate `radio:*` namespace to avoid fragmenting.

### Value bounds

Each L1 entry carries optional bounds that Spark's ingestion pipeline consumes:

| Field | Effect on Spark ingestion |
|---|---|
| `min_value` / `max_value` | Values outside this range are **rejected** before storage (physically impossible — negative cumulative volume, voltage above 1 kV on a residential meter). |
| `monotonic` | Cumulative counter that must **not decrease** between consecutive readings of the same device. Decreases trigger a quality flag (often a meter reset or memory corruption). |

Both bounds are optional. A `null` bound means *no opinion at the catalogue layer* — the consumer applies its own fallback or skips the check. We deliberately stop at hard caps + monotonic: it's a 1:1 replacement of Spark's existing `METRIC_LIMITS` and `NON_NEGATIVE_METRICS` tables, no speculative new concepts. If we later need a soft "flag-but-store" tier (i.e. `plausible_min` / `plausible_max`), that's a one-shot migration with no semantic conflict.

Validation lives only at L1 — no per-DeviceType (L2) or per-VendorModel (L4) overrides yet. The 3-phase-industrial vs. residential-single-phase question is real but rare enough that we'd rather wait for a concrete case than scaffold the override machinery. When it appears, the slot is obvious: L4 `field_mappings` already carries `scale`/`offset` per entry; bounds fit alongside.

Migration `0031_metric_value_bounds` seeds conservative defaults for the ~30 standard metrics — wide caps (anything beyond physics is rejected). Operators tighten them from the metric admin as needed.

Auto-created Metric rows (from `ProcessorConfig.save()` discovering unknown targets) start with **all bounds null** — they take no opinion until an operator dials them in. This keeps the tolerant auto-create pattern from accidentally introducing rejection rules.

### How Spark sees the bounds

Two redundant paths, by design:

1. **Top-level `metrics` array** in `/api/v1/sync/` and `/api/v1/library/content/<v>/` — the full L1 catalogue (same shape as the YAML manifest). Spark can cache this as its own metric dictionary keyed by `key`. Useful when Spark needs the bounds for a metric that isn't currently mapped on any specific device (overview screens, global validation, charts on aggregates).

2. **Denormalized per-entry** in `VendorModel.effective_field_mappings`. Each mapped field carries `min_value` / `max_value` / `monotonic` inlined from the matching L1 row (omitted when null/false to keep the payload small). Spark's ingestion path reads `entry["min_value"]` directly without a separate L1 lookup — same access pattern as `label`, `unit`, `tier` today.

```json
{
  "source": "vol_m3",
  "target": "water:total_volume",
  "label": "Total Volume",
  "unit": "m³",
  "tier": "primary",
  "min_value": "0.000000",
  "max_value": "1000000000.000000",
  "monotonic": true
}
```

The two paths intentionally overlap. Spark can pick whichever fits the call site — the per-entry view for hot ingestion, the top-level catalogue for everything else.

---

## L2 — DeviceType profile

```yaml
device_type: heat_meter
metrics:
  - {metric: heat:total_energy, tier: primary}
  - {metric: heat:total_volume, tier: primary}
  - {metric: heat:flow_temp,    tier: secondary}
  - {metric: heat:return_temp,  tier: secondary}
  - {metric: device:battery,    tier: diagnostic}
  - {metric: device:rssi,       tier: diagnostic}
```

Three exclusive tiers (consumer-side UX intent):
- `primary` — shown by default on charts and overviews
- `secondary` — hidden by default, user can toggle on (checkbox / chart series picker)
- `diagnostic` — admin-only, hidden from end users entirely

---

## L3 + L4 per technology

### Modbus

**L3:**
```yaml
register_definitions:
  - {address: 0x0010, data_type: float32, scale: 0.001, field: energy_kwh, unit: kWh}
```
→ `{energy_kwh: 1234.5}`

**L4:**
```yaml
- {source: energy_kwh, target: heat:total_energy}
```

### wM-Bus

**L3** — external `wmbusmeters` decoder does the work; we just pick a driver (`auto` lets it detect the manufacturer):
```yaml
wmbus_config:
  manufacturer_code: ZRI
  wmbus_device_type: 8
  wmbusmeters_driver: auto    # or vendor-specific driver name
  encryption_required: true
```
→ wmbusmeters output: `{consumption_hca: 1342, target_hca: 1100, base_hca: 200, …}` (field names follow the driver)

**L4:**
```yaml
- {source: consumption_hca, target: heat:total_consumption}
- {source: target_hca,      target: heat:consumption_at_set_date}
```

`WMBusConfig.data_record_mapping` exists as an escape hatch for manually defining DR-level decoding when wmbusmeters isn't enough — rare in practice.

### LoRaWAN (vendor codec, not modified)

**L3:**
```js
function decodeUplink(input) {
  return {data: {energy_wh: input.bytes[0] * 100}};  // vendor emits Wh
}
```
→ `{energy_wh: 123400}`

**L4** — `scale` compensates for the non-canonical unit (we don't fork the vendor codec):
```yaml
- {source: energy_wh, target: heat:total_energy, scale: 0.001}
```

For an `°F → °C` device the same shape covers offset too: `{source: temp_f, target: env:temperature, scale: 0.5556, offset: -17.78}`.

---

## Multi-channel (3-phase, multi-tariff)

Each channel = a separate L1 metric. The catalogue grows by N entries
(e.g. `elec:voltage_l1`, `elec:voltage_l2`, `elec:voltage_l3`) but the
data model stays flat — one entry per decoded source field.

```yaml
# L1 — three entries, one per phase
- {key: elec:voltage_l1, label: "Voltage L1", unit: V, data_type: decimal}
- {key: elec:voltage_l2, label: "Voltage L2", unit: V, data_type: decimal}
- {key: elec:voltage_l3, label: "Voltage L3", unit: V, data_type: decimal}

# L4 — straight 1:1 source → target
- {source: voltage_l1, target: elec:voltage_l1}
- {source: voltage_l2, target: elec:voltage_l2}
- {source: voltage_l3, target: elec:voltage_l3}
```

Consumers query by `target` directly. Same pattern for multi-tariff (`elec:energy_t1`, `elec:energy_t2`, …).

---

## Effective API output

```json
{
  "source": "energy_wh",
  "target": "heat:total_energy",
  "label": "Total Energy",
  "unit": "kWh",
  "tier": "primary",
  "scale": 0.001
}
```

`label`, `unit`, `tier` resolved from L1+L2 (not stored per entry). `scale`, `offset` come from L4 and are emitted only when non-default (scale ≠ 1, offset ≠ 0).

---

## Migration

- Seed L1 from unique `target` values across existing mappings; manual dedup pass (today's targets are free-text — expect `total_energy` vs `Total Energy` vs `total energy`).
- Aggregate per type → seed L2 (default `tier: secondary`, manually promote primaries).
- Drop `unit` from L4 entries (now resolved from L1). Keep `target` as the per-entry key (Spark continues to read `entry["target"]`).
- Drop legacy `transform` strings — type-coercion (`to_float`/`identity`) moves to L1 `data_type`; unit conversion lives in `scale`/`offset` going forward.
- Validate every L4 entry against L1 (with tolerant auto-create for vendor-specific metrics).
- ~4–5 days. Spark and Mobile untouched (API shape stays a flat list with the same `target` key).
