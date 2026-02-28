"""Library models — device definitions and metadata."""

import secrets
import uuid

from django.conf import settings
from django.db import models
from model_utils.models import TimeStampedModel


class Vendor(TimeStampedModel):
    """Device vendor / manufacturer."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class DeviceType(TimeStampedModel):
    """A device type definition."""

    class DeviceCategory(models.TextChoices):
        POWER_METER = "power_meter", "Power Meter"
        GATEWAY = "gateway", "Gateway"
        ENVIRONMENT_SENSOR = "environment_sensor", "Environment Sensor"
        WATER_METER = "water_meter", "Water Meter"
        HEAT_METER = "heat_meter", "Heat Meter"
        HEAT_COST_ALLOCATOR = "heat_cost_allocator", "Heat Cost Allocator"

    class Technology(models.TextChoices):
        MODBUS = "modbus", "Modbus"
        LORAWAN = "lorawan", "LoRaWAN"
        WMBUS = "wmbus", "wM-Bus"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="device_types")
    model_number = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    device_type = models.CharField(max_length=30, choices=DeviceCategory.choices)
    technology = models.CharField(max_length=20, choices=Technology.choices)
    description = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["vendor__name", "model_number"]
        unique_together = [("vendor", "model_number")]

    def __str__(self):
        return f"{self.vendor.name} {self.model_number}"


class ModbusConfig(TimeStampedModel):
    """Modbus-specific configuration for a device type."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(DeviceType, on_delete=models.CASCADE, related_name="modbus_config")
    function = models.CharField(max_length=50, blank=True, default="")
    byte_order = models.CharField(max_length=50, blank=True, default="")
    word_order = models.CharField(max_length=50, blank=True, default="")

    def __str__(self):
        return f"ModbusConfig for {self.device_type}"


class RegisterDefinition(TimeStampedModel):
    """A single Modbus register definition."""

    class DataType(models.TextChoices):
        INT16 = "int16", "int16"
        UINT16 = "uint16", "uint16"
        INT32 = "int32", "int32"
        UINT32 = "uint32", "uint32"
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

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(DeviceType, on_delete=models.CASCADE, related_name="lorawan_config")
    device_class = models.CharField(max_length=1, choices=DeviceClass.choices, blank=True, default="")
    downlink_f_port = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f"LoRaWANConfig for {self.device_type}"


class WMBusConfig(TimeStampedModel):
    """wM-Bus-specific configuration for a device type."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(DeviceType, on_delete=models.CASCADE, related_name="wmbus_config")
    manufacturer_code = models.CharField(max_length=10, blank=True, default="")
    wmbus_device_type = models.IntegerField(null=True, blank=True)
    data_record_mapping = models.JSONField(default=list, blank=True)
    encryption_required = models.BooleanField(default=False)
    shared_encryption_key = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"WMBusConfig for {self.device_type}"


class ControlConfig(TimeStampedModel):
    """Control capabilities for a device type."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(DeviceType, on_delete=models.CASCADE, related_name="control_config")
    controllable = models.BooleanField(default=False)
    capabilities = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"ControlConfig for {self.device_type}"


class ProcessorConfig(TimeStampedModel):
    """Processor/decoder configuration for a device type."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_type = models.OneToOneField(DeviceType, on_delete=models.CASCADE, related_name="processor_config")
    decoder_type = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"ProcessorConfig for {self.device_type}"


class LibraryVersion(TimeStampedModel):
    """A published version of the device library."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.CharField(max_length=20, unique=True)
    schema_version = models.IntegerField(default=2)
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
    """Tracks which devices were changed in a library version."""

    class ChangeType(models.TextChoices):
        ADDED = "added", "Added"
        MODIFIED = "modified", "Modified"
        REMOVED = "removed", "Removed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    library_version = models.ForeignKey(LibraryVersion, on_delete=models.CASCADE, related_name="device_changes")
    device_type = models.ForeignKey(DeviceType, on_delete=models.CASCADE, related_name="version_changes")
    change_type = models.CharField(max_length=20, choices=ChangeType.choices)

    class Meta:
        unique_together = [("library_version", "device_type")]

    def __str__(self):
        return f"{self.get_change_type_display()}: {self.device_type}"


def generate_api_key():
    return secrets.token_urlsafe(48)


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
