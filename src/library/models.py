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
DEFAULT_SCHEMA_VERSION = 3


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
    """A first-class device type — water_meter, gas_meter, heat_meter, …

    Carries the shared *default field mappings* that VendorModels of this
    type inherit when their own override list is empty. A mapping entry
    has the shape ``{source, target, transform, primary?}`` — ``primary``
    is a per-entry boolean (default false ⇒ secondary), so display tier
    travels with the mapping itself instead of being maintained as a
    separate ``primary_field_names`` list.

    Per-meter knobs that genuinely vary between instances of the same
    type — offline window, controllability — live on ``VendorModel`` and
    ``ControlConfig`` instead.

    Identity is the ``code`` slug (matches the historical ``DeviceCategory``
    enum values used on ``VendorModel.device_type``); ``key`` is the UUID
    used by sync clients (Spark) to refer to this row across instances.
    """

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
    default_field_mappings = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Default codec → canonical-metric mappings shared by every "
            "VendorModel of this type. Each entry is "
            "{source, target, transform, primary?} — primary defaults to false "
            "(⇒ secondary). VendorModels can replace the whole list via "
            "ProcessorConfig.field_mappings or extend it via "
            "ProcessorConfig.extra_field_mappings."
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
        """Resolve the effective list of codec→metric mappings for this model.

        ``ProcessorConfig.field_mappings`` (per-model) replaces the
        ``DeviceType.default_field_mappings`` when non-empty, otherwise the
        type defaults are used. ``ProcessorConfig.extra_field_mappings``
        (vendor-specific extras) is always concatenated on top.
        """
        proc = getattr(self, "processor_config", None)
        base: list[dict] = []
        if proc and proc.field_mappings:
            base = list(proc.field_mappings)
        elif self.device_type_fk_id:
            base = list(self.device_type_fk.default_field_mappings or [])
        if proc and proc.extra_field_mappings:
            base.extend(proc.extra_field_mappings)
        return base

    @property
    def primary_targets(self) -> list[str]:
        """Targets from ``effective_field_mappings`` flagged as primary."""
        return [m.get("target") for m in self.effective_field_mappings if m.get("primary")]

    @property
    def secondary_targets(self) -> list[str]:
        """Targets from ``effective_field_mappings`` not flagged as primary."""
        return [m.get("target") for m in self.effective_field_mappings if not m.get("primary")]

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
    """Control capabilities for a device type."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(VendorModel, on_delete=models.CASCADE, related_name="control_config")
    controllable = models.BooleanField(default=False)
    capabilities = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"ControlConfig for {self.device_type}"


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
            "Per-model codec → canonical-metric mappings. When non-empty this "
            "list REPLACES the DeviceType.default_field_mappings entirely. "
            "Leave empty to inherit the type defaults."
        ),
    )
    extra_field_mappings = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Vendor-specific extras always concatenated on top of the "
            "effective base list (override or default). Use for telemetry "
            "unique to this model — e.g. battery, signal strength."
        ),
    )

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
