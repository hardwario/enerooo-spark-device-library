"""Library models — device definitions and metadata."""

import secrets
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from model_utils.models import TimeStampedModel

# Wire-format version emitted in /api/v1/sync/, /api/v1/manifest/,
# /api/v1/library/content/<v>/ and manifest.yaml exports. Bump when the
# payload shape changes in a way clients must opt into.
DEFAULT_SCHEMA_VERSION = 4


class Metric(TimeStampedModel):
    """L1 — Global catalogue of canonical metrics the platform understands.

    Each VendorModel field mapping points at one of these via ``metric=key``.
    The catalogue is the single source of truth for **what** a metric is —
    its label, canonical unit, data type, and *value bounds* (``min_value``
    / ``max_value`` hard caps, ``monotonic`` flag for cumulative
    counters). Tier (primary / secondary / diagnostic) is *not* on the
    metric itself; it lives on each DeviceType's profile (L2), because
    the same metric can be primary on one device type and diagnostic on
    another.

    Key convention: ``<namespace>:<name>``. The namespace prefix is
    **semantic**, not cosmetic — ``heat:total_energy`` (calorific, kWh) and
    ``elec:total_energy`` (electrical, kWh) are different physical
    quantities even though both share kWh as the unit. Cross-domain
    prefixes (``device:``, ``radio:``) carry metrics that aren't tied to a
    measurement domain (battery level, signal strength, firmware health).

    Validation policy (consumed by Spark's ingestion pipeline):

    - Outside ``[min_value, max_value]`` → **reject** (data is physically
      impossible, e.g. negative cumulative volume, voltage above 1 kV
      on a residential meter).
    - ``monotonic=True`` flags cumulative counters that must never
      decrease between consecutive readings of the same device.

    Bounds are optional — null means *no opinion* at the catalogue
    layer (the consumer applies its own default or skips the check).
    Mirrors Spark's existing ``METRIC_LIMITS`` + ``NON_NEGATIVE_METRICS``
    so it can replace those hardcoded tables 1:1.

    ``aggregation`` declares how the metric should be collapsed into a
    single value when a time-series is bucketed (hourly / daily /
    monthly charts). ``delta`` for cumulative counters (last − first
    per bucket = consumption in that window), ``avg`` for instantaneous
    quantities (temperature, voltage), ``last`` for stateful telemetry
    (battery, RSSI, status). ``min`` / ``max`` / ``sum`` available for
    extremes and non-monotonic event counts. This is **bucketing
    semantics only** — "current value" widgets always read the latest
    raw point regardless of this field.

    ``kind`` classifies what role the metric plays in the system:

    - ``measurement`` *(default)* — observed quantity from the device
      (temperature, energy, voltage). Rendered as chart series, alerts
      may compare against it.
    - ``state`` — mirror of a controllable property (relay on/off,
      target setpoint, HVAC mode). Paired with a control widget on the
      VendorModel via ``feedback_metric``; client UIs render it next
      to the toggle/slider/enum so the user sees the live state, not
      just the command they sent. Hidden by default from chart metric
      pickers (it's not interesting as a trend by itself).

    Future ``kind`` values (alert thresholds, composite metrics, …) slot
    in here without a schema migration. This is **a sibling concern to
    `tier`**: tier decides *where* to show a metric (primary / secondary
    / diagnostic UX slot); kind decides *what kind of thing* it is
    (data vs controllable state vs …).
    """

    class DataType(models.TextChoices):
        DECIMAL = "decimal", "Decimal"
        INTEGER = "integer", "Integer"
        BOOLEAN = "boolean", "Boolean"
        ENUM = "enum", "Enum"

    class Aggregation(models.TextChoices):
        AVG = "avg", "Average"
        LAST = "last", "Last value"
        DELTA = "delta", "Delta (last − first)"
        SUM = "sum", "Sum"
        MIN = "min", "Minimum"
        MAX = "max", "Maximum"

    class Kind(models.TextChoices):
        MEASUREMENT = "measurement", "Measurement"
        STATE = "state", "Control state"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(
        max_length=128,
        unique=True,
        help_text="Namespaced canonical key, e.g. 'heat:total_energy'. Format '<namespace>:<name>'.",
    )
    label = models.CharField(max_length=128)
    unit = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Canonical unit symbol, e.g. 'kWh', 'm³', 'dBm'. Empty for dimensionless metrics.",
    )
    data_type = models.CharField(max_length=20, choices=DataType.choices, default=DataType.DECIMAL)
    description = models.TextField(blank=True, default="")

    # Value bounds consumed by Spark for reject-on-ingest. Decimal so
    # callers can express both integer counts and fractional values
    # without separate columns.
    min_value = models.DecimalField(
        max_digits=24,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Hard lower cap. Values < min_value are rejected at ingestion.",
    )
    max_value = models.DecimalField(
        max_digits=24,
        decimal_places=6,
        null=True,
        blank=True,
        help_text="Hard upper cap. Values > max_value are rejected at ingestion.",
    )
    monotonic = models.BooleanField(
        default=False,
        help_text="True for cumulative counters that must not decrease (e.g. total_energy, total_volume).",
    )
    aggregation = models.CharField(
        max_length=10,
        choices=Aggregation.choices,
        default=Aggregation.AVG,
        help_text=(
            "How to collapse this metric into one value per time bucket "
            "in charts. 'delta' for cumulative counters, 'avg' for "
            "instantaneous quantities, 'last' for state telemetry."
        ),
    )
    kind = models.CharField(
        max_length=20,
        choices=Kind.choices,
        default=Kind.MEASUREMENT,
        help_text=(
            "What role this metric plays: 'measurement' for observed "
            "quantities (default), 'state' for mirrors of controllable "
            "device properties paired with a control widget."
        ),
    )

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return self.key

    @property
    def namespace(self) -> str:
        return self.key.split(":", 1)[0] if ":" in self.key else ""

    @property
    def name(self) -> str:
        return self.key.split(":", 1)[1] if ":" in self.key else self.key

    def clean(self):
        """Enforce ``min_value ≤ max_value`` when both are set."""
        super().clean()
        if (
            self.min_value is not None
            and self.max_value is not None
            and self.min_value > self.max_value
        ):
            raise ValidationError({"max_value": "max_value must be ≥ min_value."})


class Vendor(TimeStampedModel):
    """Device vendor / manufacturer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.UUIDField(default=uuid.uuid4, null=True, blank=True, unique=True)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DeviceType(TimeStampedModel):
    """L2 — Semantic profile for a class of device (water_meter, heat_meter, …).

    Declares **which** canonical metrics (L1 ``Metric`` keys) this device
    type tracks, and the **tier** at which each should be rendered. No
    sources, no transforms — those are decoder concerns that live on
    individual ``VendorModel`` rows.

    Tier semantics (consumer-side rendering intent):

    - ``primary``      — shown by default on charts and overviews
    - ``secondary``    — hidden by default, user can toggle on
    - ``diagnostic``   — admin-only, hidden from end users

    Identity is the ``code`` slug (matches the historical ``DeviceCategory``
    enum values used on ``VendorModel.device_type``); ``key`` is the UUID
    used by sync clients (Spark) to refer to this row across instances.
    """

    class Tier(models.TextChoices):
        PRIMARY = "primary", "Primary"
        SECONDARY = "secondary", "Secondary"
        DIAGNOSTIC = "diagnostic", "Diagnostic"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.UUIDField(default=uuid.uuid4, null=True, blank=True, unique=True)
    code = models.SlugField(max_length=64, unique=True)
    label = models.CharField(max_length=128)
    description = models.TextField(blank=True, default="")
    icon = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Lucide icon name used by clients to render this type (e.g. 'droplet', 'zap').",
    )
    metrics = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "L2 profile — list of {metric, tier} entries declaring which "
            "L1 Metric keys this device type tracks, and at which display "
            "tier. Tier ∈ {primary, secondary, diagnostic}. No sources or "
            "transforms here — those are decoder concerns on VendorModel."
        ),
    )

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return self.label or self.code


class VendorModel(TimeStampedModel):
    """A vendor model definition."""

    class DeviceCategory(models.TextChoices):
        POWER_METER = "power_meter", "Power Meter"
        GATEWAY = "gateway", "Gateway"
        ENVIRONMENT_SENSOR = "environment_sensor", "Environment Sensor"
        WATER_METER = "water_meter", "Water Meter"
        HEAT_METER = "heat_meter", "Heat Meter"
        HEAT_COST_ALLOCATOR = "heat_cost_allocator", "Heat Cost Allocator"
        GAS_METER = "gas_meter", "Gas Meter"
        THERMOSTAT_HEAD = "thermostat_head", "Thermostat Head"
        SMART_PLUG = "smart_plug", "Smart Plug"

    class Technology(models.TextChoices):
        MODBUS = "modbus", "Modbus"
        LORAWAN = "lorawan", "LoRaWAN"
        WMBUS = "wmbus", "wM-Bus"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.UUIDField(default=uuid.uuid4, null=True, blank=True, unique=True)
    vendor = models.ForeignKey(
        Vendor, on_delete=models.CASCADE, related_name="device_types"
    )
    model_number = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    # ``device_type`` (CharField enum) is kept for backward compat with sync
    # clients that read schema_v2 payloads. ``device_type_fk`` is the new
    # canonical pointer carrying the per-type metadata; new clients should
    # prefer it. The two stay in sync via a model.save() guard below.
    device_type = models.CharField(max_length=30, choices=DeviceCategory.choices)
    device_type_fk = models.ForeignKey(
        DeviceType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vendor_models",
    )
    technology = models.CharField(max_length=20, choices=Technology.choices)
    description = models.TextField(blank=True, default="")

    # Per-meter knob — overrides any DeviceType-level guidance. Null = caller
    # picks its own fallback (Spark currently uses ``Vendor.online_threshold_minutes``).
    offline_window_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Per-model expected reporting interval in seconds. Null means "
            "clients should fall back to their own default."
        ),
    )

    class Meta:
        ordering = ["vendor__name", "model_number"]
        unique_together = [("vendor", "model_number")]

    def __str__(self):
        return f"{self.vendor.name} {self.model_number}"

    @property
    def effective_field_mappings(self) -> list[dict]:
        """Resolved + merged view of L4 ``field_mappings`` and
        ``extra_mappings``, annotated with metadata from L1 + L2.

        Each entry carries the raw L4 fields plus derived fields:

        - ``label`` (from L1 ``Metric.label``)
        - ``unit``  (from L1 ``Metric.unit``)
        - ``tier``  — for ``field_mappings`` entries, resolved from
          L2 ``DeviceType.metrics``; for ``extra_mappings`` entries,
          taken from the entry's own ``tier`` field (default
          ``secondary``).
        - ``min_value`` / ``max_value`` / ``monotonic`` from L1
          (omitted when null/false). Lets Spark validate readings
          per-entry without doing its own L1 lookup.

        ``target`` is kept as the per-entry key name so existing
        decoder/Spark code that reads ``entry["target"]`` keeps working.

        Multi-channel devices (3-phase meters, etc.) model each channel
        as a separate metric (``elec:voltage_l1``, …) — no per-entry tags.

        L1 lookups are batched once per call to avoid N+1.
        """
        proc = getattr(self, "processor_config", None)
        base_entries: list[dict] = list(proc.field_mappings) if (proc and proc.field_mappings) else []
        extra_entries: list[dict] = list(proc.extra_mappings) if (proc and proc.extra_mappings) else []
        if not base_entries and not extra_entries:
            return []

        # Batch L1 lookup across both lists
        target_keys = {
            e.get("target")
            for e in (*base_entries, *extra_entries)
            if e.get("target")
        }
        metrics_by_key = {m.key: m for m in Metric.objects.filter(key__in=target_keys)}

        # L2 tier resolution (only applies to ``field_mappings`` entries —
        # extras carry tier per-entry).
        tier_by_target: dict[str, str] = {}
        if self.device_type_fk_id:
            for entry in (self.device_type_fk.metrics or []):
                if entry.get("metric") and entry.get("tier"):
                    tier_by_target[entry["metric"]] = entry["tier"]

        def _annotate(entry: dict, tier: str, prefer_entry_meta: bool) -> dict:
            target_key = entry.get("target")
            m = metrics_by_key.get(target_key)
            # For extras, prefer the entry's own label/unit (set by the
            # operator); fall back to L1 if the target happens to be in
            # the catalogue; finally fall back to the bare target key /
            # empty string.
            if prefer_entry_meta:
                label = entry.get("label") or (m.label if m else target_key)
                unit = entry.get("unit") if entry.get("unit") is not None else (m.unit if m else "")
            else:
                label = m.label if m else target_key
                unit = m.unit if m else ""
            ann = {
                "source": entry.get("source"),
                "target": target_key,
                "label": label,
                "unit": unit,
                "tier": tier,
            }
            if entry.get("scale") is not None and entry["scale"] != 1:
                ann["scale"] = entry["scale"]
            if entry.get("offset") is not None and entry["offset"] != 0:
                ann["offset"] = entry["offset"]
            # Denormalize L1 value bounds + monotonic flag so Spark can
            # validate per-entry without a separate L1 lookup. Omit
            # nulls/false to keep the wire shape compact.
            if m is not None:
                if m.min_value is not None:
                    ann["min_value"] = m.min_value
                if m.max_value is not None:
                    ann["max_value"] = m.max_value
                if m.monotonic:
                    ann["monotonic"] = True
                # ``avg`` is the default — only emit when non-default
                # so the wire shape stays compact for the common case.
                if m.aggregation and m.aggregation != Metric.Aggregation.AVG:
                    ann["aggregation"] = m.aggregation
            return ann

        result: list[dict] = []
        for entry in base_entries:
            result.append(_annotate(entry, tier_by_target.get(entry.get("target"), "diagnostic"), prefer_entry_meta=False))
        for entry in extra_entries:
            result.append(_annotate(entry, entry.get("tier") or "secondary", prefer_entry_meta=True))
        return result

    @property
    def declared_metrics(self) -> list[dict]:
        """L2 view: which metrics this model's DeviceType declares, with tier.

        Useful for coverage reporting on the API + admin (compare declared
        vs produced).
        """
        if not self.device_type_fk_id:
            return []
        return list(self.device_type_fk.metrics or [])

    def save(self, *args, **kwargs):
        """Keep ``device_type`` (charfield) aligned with ``device_type_fk.code``
        when an FK is set. Ensures schema_v2 clients see the right enum value
        even when an editor wired up the FK."""
        if self.device_type_fk_id and self.device_type_fk.code and self.device_type != self.device_type_fk.code:
            self.device_type = self.device_type_fk.code
        super().save(*args, **kwargs)


class ModbusConfig(TimeStampedModel):
    """Modbus-specific configuration for a device type."""

    class Function(models.TextChoices):
        INPUT = "input", "Input"
        HOLDING = "holding", "Holding"

    class ByteOrder(models.TextChoices):
        BIG_ENDIAN = "big_endian", "Big Endian"
        LITTLE_ENDIAN = "little_endian", "Little Endian"

    class WordOrder(models.TextChoices):
        HIGH_FIRST = "high_first", "High First"
        LOW_FIRST = "low_first", "Low First"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(VendorModel, on_delete=models.CASCADE, related_name="modbus_config")
    function = models.CharField(max_length=50, choices=Function.choices, blank=True, default="")
    byte_order = models.CharField(max_length=50, choices=ByteOrder.choices, blank=True, default="")
    word_order = models.CharField(max_length=50, choices=WordOrder.choices, blank=True, default="")

    def __str__(self):
        return f"ModbusConfig for {self.device_type}"


class RegisterDefinition(TimeStampedModel):
    """A single Modbus register definition."""

    class DataType(models.TextChoices):
        INT16 = "int16", "int16"
        UINT16 = "uint16", "uint16"
        INT32 = "int32", "int32"
        UINT32 = "uint32", "uint32"
        INT64 = "int64", "int64"
        UINT64 = "uint64", "uint64"
        FLOAT32 = "float32", "float32"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    modbus_config = models.ForeignKey(ModbusConfig, on_delete=models.CASCADE, related_name="register_definitions")
    field_name = models.CharField(max_length=255)
    field_unit = models.CharField(max_length=50, blank=True, default="")
    address = models.IntegerField()
    data_type = models.CharField(max_length=20, choices=DataType.choices)
    scale = models.FloatField(default=1.0)
    offset = models.FloatField(default=0.0)

    class Meta:
        ordering = ["address"]

    def __str__(self):
        return f"{self.field_name} @ {self.address}"


class LoRaWANConfig(TimeStampedModel):
    """LoRaWAN-specific configuration for a device type."""

    class DeviceClass(models.TextChoices):
        A = "A", "Class A"
        B = "B", "Class B"
        C = "C", "Class C"

    class CodecFormat(models.TextChoices):
        TTN_V3 = "ttn_v3", "TTN v3 (decodeUplink / encodeDownlink)"
        TTN_V2 = "ttn_v2", "TTN v2 Legacy (Decoder / Encoder)"
        CHIRPSTACK = "chirpstack", "ChirpStack v4"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(VendorModel, on_delete=models.CASCADE, related_name="lorawan_config")
    device_class = models.CharField(max_length=1, choices=DeviceClass.choices, blank=True, default="")
    downlink_f_port = models.IntegerField(null=True, blank=True)
    codec_format = models.CharField(
        max_length=16,
        choices=CodecFormat.choices,
        default=CodecFormat.TTN_V3,
        blank=True,
    )
    payload_codec = models.TextField(
        blank=True,
        default="",
        help_text="JavaScript source implementing decodeUplink/encodeDownlink (TTN v3/ChirpStack) or Decoder/Encoder (TTN v2).",
    )
    field_map = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"LoRaWANConfig for {self.device_type}"


class WMBusConfig(TimeStampedModel):
    """wM-Bus-specific configuration for a device type."""

    WMBUS_DEVICE_TYPE_LABELS = {
        0x00: "Other",
        0x01: "Oil Meter",
        0x02: "Electricity Meter",
        0x03: "Gas Meter",
        0x04: "Heat Meter",
        0x05: "Steam Meter",
        0x06: "Warm Water Meter",
        0x07: "Water Meter",
        0x08: "Heat Cost Allocator",
        0x09: "Compressed Air",
        0x0A: "Cooling Meter (outlet)",
        0x0B: "Cooling Meter (inlet)",
        0x0C: "Heat Meter (inlet)",
        0x0D: "Combined Heat/Cooling",
        0x0E: "Bus/System Component",
        0x0F: "Unknown",
        0x15: "Hot Water Meter",
        0x16: "Cold Water Meter",
        0x17: "Hot/Cold Water Meter",
        0x1A: "Smoke Detector",
        0x1B: "Room Sensor",
        0x1C: "Gas Detector",
        0x20: "Breaker (electricity)",
        0x21: "Valve (gas or water)",
        0x25: "Customer Unit (display)",
        0x28: "Waste Water Meter",
        0x29: "Garbage",
        0x37: "Radio Converter (meter side)",
        0x39: "Radio Converter (system side)",
    }

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(VendorModel, on_delete=models.CASCADE, related_name="wmbus_config")
    manufacturer_code = models.CharField(max_length=10, blank=True, default="")
    wmbus_version = models.CharField(max_length=4, blank=True, default="", help_text="Hex byte from telegram header, e.g. 1b")
    wmbus_device_type = models.IntegerField(null=True, blank=True)
    data_record_mapping = models.JSONField(default=list, blank=True)
    encryption_required = models.BooleanField(default=False)
    shared_encryption_key = models.CharField(max_length=32, blank=True, default="")

    wmbusmeters_driver = models.CharField(max_length=100, blank=True, default="auto")
    field_map = models.JSONField(default=dict, blank=True)
    is_mvt_default = models.BooleanField(default=False)

    @property
    def wmbus_device_type_label(self):
        if self.wmbus_device_type is None:
            return None
        return self.WMBUS_DEVICE_TYPE_LABELS.get(self.wmbus_device_type, f"Unknown (0x{self.wmbus_device_type:02X})")

    def clean(self):
        super().clean()
        if self.is_mvt_default:
            dup = (
                WMBusConfig.objects.filter(
                    manufacturer_code=self.manufacturer_code,
                    wmbus_version=self.wmbus_version,
                    wmbus_device_type=self.wmbus_device_type,
                    is_mvt_default=True,
                )
                .exclude(pk=self.pk)
            )
            if dup.exists():
                existing = dup.select_related("device_type").first()
                raise ValidationError(
                    f"Another device already has is_mvt_default set for "
                    f"manufacturer_code={self.manufacturer_code!r}, "
                    f"wmbus_version={self.wmbus_version!r}, "
                    f"wmbus_device_type={self.wmbus_device_type}: "
                    f"{existing.device_type}"
                )

    def __str__(self):
        return f"WMBusConfig for {self.device_type}"


class ControlConfig(TimeStampedModel):
    """L4-control — Per-VendorModel control widgets (the inverse direction
    of ``ProcessorConfig.field_mappings``: user actions → wire commands).

    Each device that can be controlled (``controllable=True``) carries a
    typed list of ``controls`` declaring **what** can be controlled
    (widget kind), **how** it's encoded on the wire (per technology),
    and **what L1 metric reflects the resulting state** so client UIs
    can render live feedback next to the widget.

    Schema of a single control entry::

        {
          "id":               <str>,           # stable handle (e.g. "power", "target_temp")
          "label":            <str>,
          "widget":           "toggle" | "enum" | "slider" | "button",
          "feedback_metric":  <metric.key>,    # L1 Metric with kind="state", optional for buttons
          "requires_confirmation": <bool>,     # optional, default false
          "group":            <str>,           # optional grouping for UI
          # ---- widget-specific ----
          "states":   {<name>: {"wire": {...}}, ...}  # toggle
          "options":  [{"value": ..., "label": ..., "wire": {...}}, ...]  # enum
          "min":/"max":/"step":/"unit":/"default": ...; "wire": {..., "payload_template": "..."}  # slider
          "wire":     {...}  # button
        }

    The ``wire`` object's shape depends on the parent VendorModel's
    technology — see ``docs/architecture/controls-architecture.md`` for
    the per-technology vocabulary (LoRaWAN ``f_port`` + ``payload_hex``,
    MQTT ``topic`` + ``payload``, Modbus ``register`` + ``value``).
    """

    class Widget(models.TextChoices):
        TOGGLE = "toggle", "Toggle (on/off)"
        ENUM = "enum", "Enum (pick one)"
        SLIDER = "slider", "Slider (continuous)"
        BUTTON = "button", "Button (momentary)"

    VALID_WIDGETS = {w.value for w in Widget}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(VendorModel, on_delete=models.CASCADE, related_name="control_config")
    controllable = models.BooleanField(default=False)
    controls = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "List of typed control widgets. Each entry has id/label/"
            "widget/wire + widget-specific fields. See ControlConfig "
            "docstring for the full schema."
        ),
    )

    def __str__(self):
        return f"ControlConfig for {self.device_type}"

    def clean(self):
        """Validate the structured ``controls`` list.

        Per-widget required fields:

        - ``toggle`` → ``states`` dict (at least one named state with ``wire``)
        - ``enum``   → ``options`` list (each with ``value`` + ``wire``)
        - ``slider`` → ``min``, ``max`` (numeric) + ``wire`` with ``payload_template``
        - ``button`` → ``wire``

        ``feedback_metric`` (when set) must reference an existing Metric
        with ``kind=state`` — validated lazily so legacy data doesn't
        break ``full_clean()``.
        """
        super().clean()
        if not isinstance(self.controls, list):
            raise ValidationError({"controls": "Must be a list of control entries."})

        seen_ids: set[str] = set()
        for idx, entry in enumerate(self.controls):
            if not isinstance(entry, dict):
                raise ValidationError({"controls": f"Entry #{idx} must be an object."})
            cid = entry.get("id")
            if not cid or not isinstance(cid, str):
                raise ValidationError({"controls": f"Entry #{idx} missing string ``id``."})
            if cid in seen_ids:
                raise ValidationError({"controls": f"Duplicate control id ``{cid}``."})
            seen_ids.add(cid)
            widget = entry.get("widget")
            if widget not in self.VALID_WIDGETS:
                raise ValidationError({"controls": (
                    f"Entry ``{cid}``: widget must be one of "
                    f"{sorted(self.VALID_WIDGETS)}, got {widget!r}."
                )})

            if widget == self.Widget.TOGGLE:
                states = entry.get("states")
                if not isinstance(states, dict) or not states:
                    raise ValidationError({"controls": (
                        f"Toggle ``{cid}`` requires a non-empty ``states`` dict."
                    )})
                for name, st in states.items():
                    if not isinstance(st, dict) or "wire" not in st:
                        raise ValidationError({"controls": (
                            f"Toggle ``{cid}`` state ``{name}`` must have a ``wire`` object."
                        )})

            elif widget == self.Widget.ENUM:
                options = entry.get("options")
                if not isinstance(options, list) or not options:
                    raise ValidationError({"controls": (
                        f"Enum ``{cid}`` requires a non-empty ``options`` list."
                    )})
                seen_values = set()
                for opt in options:
                    if not isinstance(opt, dict) or "value" not in opt or "wire" not in opt:
                        raise ValidationError({"controls": (
                            f"Enum ``{cid}`` each option must have ``value`` and ``wire``."
                        )})
                    if opt["value"] in seen_values:
                        raise ValidationError({"controls": (
                            f"Enum ``{cid}`` duplicate option value ``{opt['value']}``."
                        )})
                    seen_values.add(opt["value"])

            elif widget == self.Widget.SLIDER:
                if "min" not in entry or "max" not in entry:
                    raise ValidationError({"controls": (
                        f"Slider ``{cid}`` requires numeric ``min`` and ``max``."
                    )})
                try:
                    lo = float(entry["min"])
                    hi = float(entry["max"])
                except (TypeError, ValueError):
                    raise ValidationError({"controls": (
                        f"Slider ``{cid}`` ``min``/``max`` must be numeric."
                    )}) from None
                if lo > hi:
                    raise ValidationError({"controls": (
                        f"Slider ``{cid}`` ``min`` must be <= ``max``."
                    )})
                wire = entry.get("wire")
                if not isinstance(wire, dict) or not any(
                    k in wire for k in ("payload_template", "register", "topic")
                ):
                    raise ValidationError({"controls": (
                        f"Slider ``{cid}`` wire must include payload_template/"
                        f"register/topic for value binding."
                    )})

            elif widget == self.Widget.BUTTON:
                if not isinstance(entry.get("wire"), dict):
                    raise ValidationError({"controls": (
                        f"Button ``{cid}`` requires a ``wire`` object."
                    )})


class ProcessorConfig(TimeStampedModel):
    """Processor/decoder configuration for a device type."""

    class DecoderType(models.TextChoices):
        WMBUS_FIELD_MAP = "wmbus_field_map", "wM-Bus Field Map"
        LORAWAN_FIELD_MAP = "lorawan_field_map", "LoRaWAN Field Map"
        JS_CODEC = "js_codec", "JS Codec (QuickJS)"
        CONFIGURABLE = "configurable", "Configurable"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(VendorModel, on_delete=models.CASCADE, related_name="processor_config")
    decoder_type = models.CharField(max_length=255, choices=DecoderType.choices, blank=True, default="")
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra config (e.g. measurement_type) passed to Spark processor",
    )
    field_mappings = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "L4 — list of {source, target, scale?, offset?} entries "
            "mapping this model's decoded fields onto canonical L1 Metric "
            "keys declared on the parent DeviceType (L2 profile). Each "
            "entry must have a ``target`` matching one of the type's "
            "declared metrics; the editor scaffolds rows from L2 so this "
            "is enforced visually. ``scale`` (default 1) and ``offset`` "
            "(default 0) apply a linear conversion ``value * scale + "
            "offset`` — used when the decoder can't emit canonical units. "
            "For metrics not declared on the type, use ``extra_mappings``."
        ),
    )
    extra_mappings = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Per-model extras — metrics this specific VendorModel produces "
            "that aren't declared on the parent DeviceType and that the "
            "operator chose not to promote into the L1 catalogue. "
            "Each entry: {source, target, tier, label?, unit?, scale?, "
            "offset?}. ``tier`` is per-entry (primary / secondary / "
            "diagnostic). ``label`` and ``unit`` live on the entry itself "
            "(no L1 row required) — if the target happens to match an "
            "existing L1 key, the catalogue's label/unit is used as a "
            "fallback. Targets are NOT auto-created in L1 for this list."
        ),
    )

    def save(self, *args, **kwargs):
        """Auto-derive ``decoder_type`` from the parent VendorModel's
        technology and auto-create any missing L1 Metric rows referenced
        by entries.

        Decoder-type derivation:
        - wmbus  → ``wmbus_field_map``
        - lorawan → ``js_codec`` if a payload codec is configured,
                    else ``lorawan_field_map``
        - modbus → left empty (modbus decodes via RegisterDefinition, not
                   field_mappings; ProcessorConfig is rarely used)

        Operators can still set a non-default ``decoder_type`` (e.g.
        ``configurable``) explicitly via API/admin — auto-derive only fills
        in when the field is blank.

        Tolerant metric auto-create: a VendorModel can declare a metric
        the catalogue doesn't know yet (e.g. ``temp:temperature_boiler``).
        We create a minimal Metric row so downstream lookups don't fail;
        the operator dials in label/unit/data_type later in admin.
        """
        if not self.decoder_type:
            try:
                technology = self.device_type.technology
            except Exception:
                technology = None
            if technology == "wmbus":
                self.decoder_type = self.DecoderType.WMBUS_FIELD_MAP
            elif technology == "lorawan":
                has_codec = False
                try:
                    has_codec = bool(self.device_type.lorawan_config.payload_codec)
                except Exception:
                    pass
                self.decoder_type = (
                    self.DecoderType.JS_CODEC if has_codec else self.DecoderType.LORAWAN_FIELD_MAP
                )

        # Auto-create L1 Metric rows for ``field_mappings`` entries only —
        # those reference L2-declared metrics that need a catalogue anchor.
        # ``extra_mappings`` entries are intentionally device-specific
        # (label + unit live on each entry); we don't pollute the catalogue
        # with one-off keys.
        for entry in (self.field_mappings or []):
            target_key = entry.get("target")
            if not target_key:
                continue
            Metric.objects.get_or_create(
                key=target_key,
                defaults={
                    "label": target_key.split(":", 1)[-1].replace("_", " ").title(),
                    "data_type": Metric.DataType.DECIMAL,
                },
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"ProcessorConfig for {self.device_type}"


class DeviceHistory(TimeStampedModel):
    """Tracks full snapshots of device definitions on every change."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device = models.ForeignKey(
        "VendorModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history",
    )
    device_label = models.CharField(max_length=255)
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=10, choices=Action.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_history",
    )
    snapshot = models.JSONField(default=dict)
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created"]
        unique_together = [("device", "version")]
        indexes = [
            models.Index(fields=["device", "-created"]),
        ]

    def __str__(self):
        return f"v{self.version} {self.action} — {self.device_label}"


class LibraryVersion(TimeStampedModel):
    """A published version of the device library."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(unique=True)
    schema_version = models.IntegerField(default=DEFAULT_SCHEMA_VERSION)
    released_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, default="")
    is_current = models.BooleanField(default=False)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_versions",
    )

    class Meta:
        ordering = ["-released_at"]

    def __str__(self):
        return f"v{self.version}"

    def save(self, *args, **kwargs):
        if self.is_current:
            LibraryVersion.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class LibraryVersionDevice(TimeStampedModel):
    """Tracks device manifest entries for a library version."""

    class ChangeType(models.TextChoices):
        ADDED = "added", "Added"
        MODIFIED = "modified", "Modified"
        REMOVED = "removed", "Removed"
        UNCHANGED = "unchanged", "Unchanged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library_version = models.ForeignKey(LibraryVersion, on_delete=models.CASCADE, related_name="device_changes")
    device_type = models.ForeignKey(
        VendorModel, on_delete=models.SET_NULL, null=True, blank=True, related_name="version_changes"
    )
    device_version = models.PositiveIntegerField(default=1)
    device_label = models.CharField(max_length=255, default="")
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)

    class Meta:
        ordering = ["change_type", "device_label"]

    def __str__(self):
        return f"{self.get_change_type_display()}: {self.device_label}"


# -----------------------------------------------------------------------------
# L1 / L2 versioning — same audit pattern as DeviceHistory / LibraryVersionDevice
# above, applied to Metric and DeviceType. Without these, a published
# LibraryVersion couldn't faithfully reproduce the L1 catalogue and L2 type
# profiles at that point in time — operators editing a metric's bounds or a
# type's tier list would retroactively change every historical version. The
# four models below close that gap.
# -----------------------------------------------------------------------------


class MetricHistory(TimeStampedModel):
    """Full snapshot of an L1 Metric on every change. Mirrors
    ``DeviceHistory`` row-for-row so the publish / retrieve flow has
    one access pattern across the three entity types it tracks."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    metric = models.ForeignKey(
        Metric,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history",
    )
    metric_key = models.CharField(max_length=128, default="")
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=10, choices=Action.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="metric_history",
    )
    snapshot = models.JSONField(default=dict)
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created"]
        unique_together = [("metric", "version")]
        indexes = [
            models.Index(fields=["metric", "-created"]),
        ]

    def __str__(self):
        return f"v{self.version} {self.action} — {self.metric_key}"


class DeviceTypeHistory(TimeStampedModel):
    """Full snapshot of an L2 DeviceType profile on every change.
    Same shape as ``DeviceHistory`` / ``MetricHistory`` — version
    bumps on every save, snapshot carries the row state, changes
    carries a diff against the previous snapshot."""

    class Action(models.TextChoices):
        CREATED = "created", "Created"
        UPDATED = "updated", "Updated"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.ForeignKey(
        DeviceType,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="history",
    )
    device_type_code = models.CharField(max_length=64, default="")
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=10, choices=Action.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="device_type_history",
    )
    snapshot = models.JSONField(default=dict)
    changes = models.JSONField(default=dict)

    class Meta:
        ordering = ["-created"]
        unique_together = [("device_type", "version")]
        indexes = [
            models.Index(fields=["device_type", "-created"]),
        ]

    def __str__(self):
        return f"v{self.version} {self.action} — {self.device_type_code}"


class LibraryVersionMetric(TimeStampedModel):
    """Per-LibraryVersion manifest entry for a Metric — points at the
    ``MetricHistory.version`` snapshot that was the row's state when
    this LibraryVersion was published. Mirrors ``LibraryVersionDevice``."""

    class ChangeType(models.TextChoices):
        ADDED = "added", "Added"
        MODIFIED = "modified", "Modified"
        REMOVED = "removed", "Removed"
        UNCHANGED = "unchanged", "Unchanged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library_version = models.ForeignKey(
        LibraryVersion, on_delete=models.CASCADE, related_name="metric_changes",
    )
    metric = models.ForeignKey(
        Metric, on_delete=models.SET_NULL, null=True, blank=True, related_name="version_changes",
    )
    metric_version = models.PositiveIntegerField(default=1)
    metric_key = models.CharField(max_length=128, default="")
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)

    class Meta:
        ordering = ["change_type", "metric_key"]

    def __str__(self):
        return f"{self.get_change_type_display()}: {self.metric_key}"


class LibraryVersionDeviceType(TimeStampedModel):
    """Per-LibraryVersion manifest entry for a DeviceType. Mirrors
    ``LibraryVersionDevice`` and ``LibraryVersionMetric``."""

    class ChangeType(models.TextChoices):
        ADDED = "added", "Added"
        MODIFIED = "modified", "Modified"
        REMOVED = "removed", "Removed"
        UNCHANGED = "unchanged", "Unchanged"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library_version = models.ForeignKey(
        LibraryVersion, on_delete=models.CASCADE, related_name="device_type_changes",
    )
    device_type = models.ForeignKey(
        DeviceType, on_delete=models.SET_NULL, null=True, blank=True, related_name="version_changes",
    )
    device_type_version = models.PositiveIntegerField(default=1)
    device_type_code = models.CharField(max_length=64, default="")
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)

    class Meta:
        ordering = ["change_type", "device_type_code"]

    def __str__(self):
        return f"{self.get_change_type_display()}: {self.device_type_code}"


def generate_api_key():
    return secrets.token_urlsafe(48)


class GatewayAssignment(TimeStampedModel):
    """Gateway-to-Spark-instance assignment for bootstrap discovery."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    serial_number = models.CharField(max_length=255, unique=True, db_index=True)
    spark_url = models.URLField(max_length=500, blank=True, default="")
    is_registered = models.BooleanField(default=False)
    registered_at = models.DateTimeField(null=True, blank=True)
    is_assigned = models.BooleanField(default=False)
    assigned_at = models.DateTimeField(null=True, blank=True)
    assigned_by = models.CharField(max_length=255, blank=True, default="")
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.serial_number} -> {self.spark_url}"


class APIKey(TimeStampedModel):
    """API key for external services to access the sync API."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    key = models.CharField(max_length=255, unique=True, default=generate_api_key, db_index=True)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="api_keys",
    )

    class Meta:
        ordering = ["-created"]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def __str__(self):
        return self.name
