# Device controls architecture

The inverse direction of the data pipeline: instead of *device → bytes → decoded → L1 metric*, controls go *user action → wire bytes → device*. The schema is symmetric with `ProcessorConfig.field_mappings` but lives on `ControlConfig.controls`.

## Two new concepts

1. **`Metric.kind`** — enum on the L1 catalogue distinguishing observed data (`measurement`, default) from controllable mirrors (`state`). State metrics pair with control widgets via `feedback_metric` so client UIs render the live value next to the toggle/slider/enum.
2. **`ControlConfig.controls`** — typed list of widget descriptors per VendorModel. Replaces the previous free-form `capabilities` JSON blob (which migration `0034_drop_controlconfig_capabilities` removes outright after `0033` converts the only known shape).

## Widget primitives (v1)

Four shapes cover the 95% of IoT actuators we care about today:

| Widget | Sémantika | Examples | Required fields |
|---|---|---|---|
| `toggle`  | Binary state           | Smart plug, valve, lock                    | `states` (dict with at least one named state) |
| `enum`    | Pick 1-of-N            | HVAC mode, preset, fan speed               | `options` (list, each with `value` + `wire`) |
| `slider`  | Continuous in range    | Target temperature, brightness, valve %    | `min`, `max` (numeric), `wire.payload_template` (or `register`/`topic`) |
| `button`  | Momentary fire-and-go  | Identify, reset, force-read                | `wire` |

Future widgets (color picker, schedule, multi-dim) slot in via the same enum without a schema break.

## Schema of a control entry

```yaml
- id:                power                    # stable string handle
  label:             "Power"
  widget:            toggle
  feedback_metric:   device:relay_state       # L1 Metric with kind=state (optional for buttons)
  requires_confirmation: false                # optional, default false
  group:             "Power"                  # optional UI grouping
  # ---- widget-specific shape ----
  states:                                     # toggle
    on:  { wire: { f_port: 85, payload_hex: "01" } }
    off: { wire: { f_port: 85, payload_hex: "00" } }
```

### Slider — value binding via template

```yaml
- id:               target_temp
  label:            "Target Temperature"
  widget:           slider
  unit:             "°C"
  min:              5
  max:              30
  step:             0.5
  default:          20
  feedback_metric:  heat:setpoint
  wire:
    f_port:           86
    payload_template: "01{value:02X}"   # {value} bound from slider position
    scale:            2                  # 20°C → byte 40 (half-degree resolution)
    offset:           0
```

The `payload_template` is a printf-style placeholder filled by Spark's downlink encoder at command time. `scale`/`offset` apply a linear pre-transform (`device_value = ui_value * scale + offset`) before formatting.

### Enum

```yaml
- id:               mode
  label:            "Mode"
  widget:           enum
  feedback_metric:  device:hvac_mode
  options:
    - { value: heat, label: "Heating", wire: { f_port: 87, payload_hex: "01" } }
    - { value: cool, label: "Cooling", wire: { f_port: 87, payload_hex: "02" } }
    - { value: auto, label: "Auto",    wire: { f_port: 87, payload_hex: "03" } }
```

### Button

```yaml
- id:     identify
  label:  "Identify (blink LED)"
  widget: button
  wire:   { f_port: 90, payload_hex: "FF" }
  # No feedback_metric — fire-and-forget
```

## Wire encoding — per technology

The shape inside each `wire` block depends on the parent VendorModel's `technology`. We don't tag-union it explicitly; the consumer reads the fields that make sense for its tech.

| Technology | Required keys              | Optional keys                       |
|---|---|---|
| LoRaWAN    | `f_port`, `payload_hex` *(or* `payload_template`*)*    | `confirmed`, `priority`                       |
| MQTT       | `topic`, `payload` *(or* `payload_template`*)*         | `qos`, `retain`                               |
| Modbus     | `register`, `value` *(or* `value_template`*)*          | `function` (default `write_single_register`)  |

Slider widgets always need a `*_template` form (or another value binding field) so the value can be substituted in.

## The `feedback_metric` pattern

Every non-momentary control should reference an L1 Metric with `kind=state`. This metric is the **single source of truth for the live state of the controllable property** — it's what gets updated by the device's regular telemetry uplinks, and what UIs render alongside the widget.

```
                ┌────────────────────────────┐
   user taps    │  Mobile UI: toggle widget  │   shows
   ─────────►   │  next to "Currently: ON"   │   ◄─────  device:relay_state
                └────────┬───────────────────┘                       ▲
                         │                                            │
                         ▼ wire (LoRa downlink)                       │
                   ┌──────────────┐                                   │
                   │   Device     │ ── periodic uplink ──► Spark ─────┘
                   └──────────────┘                       decodes
                                                          relay state
```

Why this is the right architecture:

- **No duplicate data path.** State updates flow through the same ingest pipeline as data (L3 decoder → L4 mapping → L1 metric). One source of truth.
- **UI sees drift.** If a user toggles the device physically (button on the wall), the next uplink updates the metric, and the UI reflects reality without a special channel.
- **ACK confirmation is implicit.** After sending an "on" command, the UI waits for `device:relay_state` to flip to `True`. No separate ACK protocol.
- **Validation reuses L1.** `heat:setpoint` having `min_value: 5`, `max_value: 30` automatically constrains both the slider's bounds AND Spark's ingest validation of incoming values.

## What `kind` is **not**

`kind` is a sibling concern to `tier` (L2 `DeviceType.metrics[].tier`), not a replacement:

| Question | Field |
|---|---|
| *What role does this metric play in the system?* (data vs controllable mirror)         | `kind` (on L1 Metric) |
| *Where should this metric show up in the UI?* (primary chart, hidden, admin-only)      | `tier` (on L2 DeviceType profile) |

Same metric can be `kind=state, tier=primary` (smart-plug relay — user-facing toggle) or `kind=state, tier=diagnostic` (debug mode flag — admin only). They're orthogonal.

## How clients consume controls

### Sync API

`/api/v1/sync/` (and `/api/v1/library/content/<v>/`) exposes both shapes:

- **Top-level `metrics[]`** carries `kind` per L1 metric — useful for chart pickers that should hide `kind=state` by default.
- **Per-VendorModel `control_config`** carries `controls[]` — typed list of widget descriptors. (The old free-form `capabilities` blob was dropped in migration `0034`; clients that ever read it must switch to `controls`.)

### Spark — downlink encoder (separate PR)

When a user taps a widget in mobile, the API call lands in Spark. Spark looks up the matching `controls[]` entry (by device + control `id`), reads the `wire` block, encodes the payload (applies `scale`/`offset` for sliders, substitutes the template, wraps in LoRa downlink shape), and dispatches to the network server.

### Mobile — widget rendering (separate PR)

Mobile maps `widget` → Flutter component:

| `widget` | Component                        |
|---|---|
| `toggle`   | `Switch` with two visual states                          |
| `enum`     | `SegmentedButton` or `DropdownButton`                   |
| `slider`   | `Slider` with min/max from schema                       |
| `button`   | `OutlinedButton` (with optional confirmation modal)     |

The widget shows the *current* state from `feedback_metric`'s latest reading, and dispatches the matching command on user interaction.

## Migration

The existing pre-v5 shape (`capabilities: {relay: {f_port, commands}}`) is converted to typed `controls` by migration `0033_metric_kind_and_controls`. The three ENEROOO smart plugs (ER10W/11W/13W) come out the other end with a typed `toggle` widget pointing at `device:relay_state`. Migration `0034_drop_controlconfig_capabilities` then removes the now-unused legacy column.

Custom device-specific state metrics (e.g. `heat:setpoint_zone_2` on a multi-zone thermostat) can be auto-created by `ProcessorConfig.save()` when referenced — same tolerant pattern as data metrics. Operators flip them to `kind=state` afterwards in the admin if appropriate.

## Reference examples by device archetype

These three configurations cover **all four widget primitives** between them. Operators can paste them directly as the `controls` field on `ControlConfig` — every L1 metric referenced via `feedback_metric` is seeded by migration `0033_metric_kind_and_controls`, so the examples are paste-and-go.

### Smart plug — single toggle

The ENEROOO ER10W / ER11W / ER13W archetype. Already migrated automatically by `0033`.

```yaml
controls:
  - id: power
    label: "Power"
    widget: toggle
    feedback_metric: device:relay_state
    states:
      on:     { wire: { f_port: 85, payload_hex: "01" } }
      off:    { wire: { f_port: 85, payload_hex: "00" } }
      toggle: { wire: { f_port: 85, payload_hex: "02" } }
```

Notes:
- Three logical states (on/off/toggle) all dispatch on `f_port: 85` — same byte channel, different payload.
- `device:relay_state` is a boolean L1 metric (kind=state) — mobile UI shows the live relay status next to the switch.

### Thermostat head — slider + enum + button

Realistic LoRaWAN radiator-valve / room-thermostat with target setpoint, operating mode and an identify button.

```yaml
controls:
  - id: target_temp
    label: "Target Temperature"
    widget: slider
    unit: "°C"
    min: 5
    max: 30
    step: 0.5
    default: 20
    feedback_metric: heat:setpoint
    wire:
      f_port: 86
      payload_template: "01{value:02X}"   # {value} = device-side byte
      scale: 2                            # 20°C UI → byte 40 (half-degree)
      offset: 0

  - id: mode
    label: "Mode"
    widget: enum
    feedback_metric: device:hvac_mode
    options:
      - { value: heat, label: "Heating", wire: { f_port: 87, payload_hex: "01" } }
      - { value: eco,  label: "Eco",     wire: { f_port: 87, payload_hex: "02" } }
      - { value: off,  label: "Off",     wire: { f_port: 87, payload_hex: "00" } }

  - id: identify
    label: "Identify (blink LED)"
    widget: button
    wire: { f_port: 90, payload_hex: "FF" }
```

Notes:
- The slider's `scale: 2` means *the device speaks in half-degree resolution*: UI value 21.5°C becomes byte 43 (`0x2B`) in the payload. `payload_template` then formats it as `"012B"` and the downlink encoder turns that into the actual bytes.
- `default: 20` lets the mobile UI seed the slider position when there's no `heat:setpoint` reading yet.
- `identify` has no `feedback_metric` — it's a momentary fire-and-forget command.

### Smart gas valve — toggle with confirmation

A destructive operation that warrants a confirm modal. Pattern reusable for any actuator whose accidental toggle is consequential (water shut-off, smart lock, breaker).

```yaml
controls:
  - id: valve
    label: "Gas Valve"
    widget: toggle
    feedback_metric: device:valve_state         # create this L1 entry (kind=state) first
    requires_confirmation: true                 # mobile shows confirm modal before sending
    states:
      open:  { wire: { f_port: 85, payload_hex: "01" } }
      close: { wire: { f_port: 85, payload_hex: "00" } }
```

Notes:
- `device:valve_state` isn't seeded by 0033 — create it in the metric admin first (kind=state, data_type=boolean, aggregation=last).
- `requires_confirmation: true` is the cheap UX safeguard for destructive ops; mobile renders a "Close gas valve? [Cancel] [Close]" modal before dispatching.
- State names (`open`/`close`) are domain-appropriate — mobile renders them as the switch's two labels.

## Scope deliberately omitted from v1

| Concept | Why deferred |
|---|---|
| `enabled_when`  (state dependencies)         | Real but rare — wait for a concrete device that needs it |
| `min_role` (per-control RBAC)                 | Depends on org-level RBAC model — risky to scaffold blind |
| `expected_ack_seconds` (optimistic UI timeout)| Mobile concern; default ~30s in client works for now |
| Schedule widgets (time-of-day, weekly)        | Own complexity dimension; better as a separate feature |
| Color picker / multi-dim widgets              | No current device demands them |

Adding any of these later is additive (new keys on the entry, ignored by old clients) — no schema break.
