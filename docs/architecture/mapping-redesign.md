# Metric mapping architecture

Four layers, split by responsibility. L3 and L4 already exist implicitly; L1 and L2 are new.

| Layer | What | Where |
|---|---|---|
| **L1 Metric** | Global catalogue of metrics (label, unit, data_type) | Platform |
| **L2 DeviceType profile** | Which metrics this device type tracks + tier | Per type |
| **L3 Decoder** | Bytes → named dict | Per model (Modbus / wM-Bus / LoRaWAN) |
| **L4 Mapping** | Decoded field → metric, optional `transform` + `tags` | Per model |

L3 emits canonical units wherever we own the decoder config (Modbus `scale`, wmbusmeters driver). For vendor LoRaWAN codecs pulled from upstream we don't fork, L4 carries a `transform` from a closed enum (`wh_to_kwh`, `mwh_to_kwh`, `percent_to_ratio`, `c_to_k`, …) as an escape valve.

---

## L1 — Metric Catalogue

```yaml
- {key: heat:total_energy,  label: "Total Energy",  unit: kWh,   data_type: decimal}
- {key: heat:total_volume,  label: "Total Volume",  unit: m³,    data_type: decimal}
- {key: elec:voltage,       label: "Voltage",       unit: V,     data_type: decimal}
- {key: elec:current,       label: "Current",       unit: A,     data_type: decimal}
- {key: device:battery,     label: "Battery",       unit: ratio, data_type: decimal}
- {key: radio:rssi,         label: "Signal",        unit: dBm,   data_type: integer}
```

The `key` namespace prefix is semantic: `heat:total_energy` (calorific) ≠ `elec:total_energy` (electrical), same unit but different physical quantity. Cross-domain prefixes (`device:`, `radio:`) carry metrics not tied to a measurement domain.

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
  - {metric: radio:rssi,        tier: diagnostic}
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
- {source: energy_kwh, metric: heat:total_energy}
```

### wM-Bus

**L3:**
```yaml
data_record_mapping:
  - {dr: "0x04,0x07", field: energy_kwh, unit: kWh}
```
→ `{energy_kwh: 1234.5}`

**L4:**
```yaml
- {source: energy_kwh, metric: heat:total_energy}
```

### LoRaWAN (vendor codec, not modified)

**L3:**
```js
function decodeUplink(input) {
  return {data: {energy_wh: input.bytes[0] * 100}};  // vendor emits Wh
}
```
→ `{energy_wh: 123400}`

**L4:**
```yaml
- {source: energy_wh, metric: heat:total_energy, transform: wh_to_kwh}
```

---

## Multi-channel via tags

The catalogue declares each metric once; instances are distinguished by structured `tags` in L4.

```yaml
# L1 — one entry per metric (already in the catalogue above)
- {key: elec:voltage, label: "Voltage", unit: V, data_type: decimal}

# L4 — instances via tags
- {source: voltage_l1, metric: elec:voltage, tags: {phase: L1}}
- {source: voltage_l2, metric: elec:voltage, tags: {phase: L2}}
- {source: voltage_l3, metric: elec:voltage, tags: {phase: L3}}
```

Consumers query `metric=elec:voltage, tags.phase=L1`. Same pattern for multi-tariff (`tags: {tariff: T1}`), multi-zone, multi-channel HCAs.

---

## Effective API output

```json
{
  "source": "energy_wh",
  "metric": "heat:total_energy",
  "label": "Total Energy",
  "unit": "kWh",
  "tier": "primary",
  "transform": "wh_to_kwh",
  "tags": {}
}
```

`label`, `unit`, `tier` resolved from L1+L2 (not stored per entry). `transform` and `tags` come from L4.

---

## Migration

- Seed L1 from unique `target` values across existing mappings; manual dedup pass (today's targets are free-text — expect `total_energy` vs `Total Energy` vs `total energy`).
- Aggregate per type → seed L2 (default `tier: secondary`, manually promote primaries).
- Drop `unit` from L4 entries (now resolved from L1).
- Validate every L4 entry against L1.
- Define `transform` enum.
- ~4–5 days. Spark and Mobile untouched (API shape stays a flat list).
