# Metric mapping architecture

Four layers, split by responsibility. L3 and L4 already exist implicitly; L1 and L2 are new.

| Layer | What | Where |
|---|---|---|
| **L1 Metric** | Global catalogue of metrics (label, unit, data_type) | Platform |
| **L2 DeviceType profile** | Which metrics this device type tracks + tier | Per type |
| **L3 Decoder** | Bytes → named dict | Per model (Modbus / wM-Bus / LoRaWAN) |
| **L4 Mapping** | Decoded field → target metric, optional `scale` + `offset` + `tags` | Per model |

L4 entries use the key name **`target`** for the pointer at an L1 `Metric.key` — kept so existing decoders (Spark) reading `entry["target"]` keep working without code change. L2 entries use **`metric`** because they're a declaration (this type tracks this metric), not a decoder mapping.

L3 emits canonical units wherever we own the decoder config (Modbus `scale`/`offset`, wmbusmeters driver). For vendor LoRaWAN codecs we pull from upstream and don't fork, L4 carries `scale` (default 1) and `offset` (default 0) for a generic linear conversion `value * scale + offset` — covers Wh→kWh, dWh→kWh, °F→°C, %→ratio without enumerating each.

Model entries referencing a target key not yet in the L1 catalogue **auto-create** the row on save (tolerant pattern — operator tidies label/unit in admin afterwards). Lets vendors land custom metrics like `temp:temperature_boiler` without blocking on catalogue maintenance.

---

## L1 — Metric Catalogue

```yaml
- {key: heat:total_energy,  label: "Total Energy",  unit: kWh,   data_type: decimal}
- {key: heat:total_volume,  label: "Total Volume",  unit: m³,    data_type: decimal}
- {key: elec:voltage,       label: "Voltage",       unit: V,     data_type: decimal}
- {key: elec:current,       label: "Current",       unit: A,     data_type: decimal}
- {key: device:battery,     label: "Battery",       unit: ratio, data_type: decimal}
- {key: device:rssi,        label: "Signal",        unit: dBm,   data_type: integer}
- {key: device:status,      label: "Status",        unit: "",    data_type: enum}
```

The `key` namespace prefix is semantic: `heat:total_energy` (calorific) ≠ `elec:total_energy` (electrical), same unit but different physical quantity. The `device:` namespace covers cross-domain health telemetry (battery, RSSI, firmware, status) regardless of underlying technology — no separate `radio:*` namespace to avoid fragmenting.

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

## Multi-channel via tags

The catalogue declares each metric once; instances are distinguished by structured `tags` in L4.

```yaml
# L1 — one entry per metric (already in the catalogue above)
- {key: elec:voltage, label: "Voltage", unit: V, data_type: decimal}

# L4 — instances via tags
- {source: voltage_l1, target: elec:voltage, tags: {phase: L1}}
- {source: voltage_l2, target: elec:voltage, tags: {phase: L2}}
- {source: voltage_l3, target: elec:voltage, tags: {phase: L3}}
```

Consumers query `target=elec:voltage, tags.phase=L1`. Same pattern for multi-tariff (`tags: {tariff: T1}`), multi-zone, multi-channel HCAs.

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

`label`, `unit`, `tier` resolved from L1+L2 (not stored per entry). `scale`, `offset`, `tags` come from L4 and are emitted only when non-default (scale ≠ 1, offset ≠ 0, tags non-empty).

---

## Migration

- Seed L1 from unique `target` values across existing mappings; manual dedup pass (today's targets are free-text — expect `total_energy` vs `Total Energy` vs `total energy`).
- Aggregate per type → seed L2 (default `tier: secondary`, manually promote primaries).
- Drop `unit` from L4 entries (now resolved from L1). Keep `target` as the per-entry key (Spark continues to read `entry["target"]`).
- Drop legacy `transform` strings — type-coercion (`to_float`/`identity`) moves to L1 `data_type`; unit conversion lives in `scale`/`offset` going forward.
- Validate every L4 entry against L1 (with tolerant auto-create for vendor-specific metrics).
- ~4–5 days. Spark and Mobile untouched (API shape stays a flat list with the same `target` key).
