"""Library admin configuration."""

from django.contrib import admin
from django.db import models

from .forms import PrettyJSONWidget
from .models import (
    APIKey,
    ControlConfig,
    DeviceType,
    GatewayAssignment,
    LibraryVersion,
    LibraryVersionDevice,
    LoRaWANConfig,
    Metric,
    ModbusConfig,
    ProcessorConfig,
    RegisterDefinition,
    Vendor,
    VendorModel,
    WMBusConfig,
)


@admin.register(Metric)
class MetricAdmin(admin.ModelAdmin):
    list_display = ["key", "label", "unit", "data_type", "monotonic", "min_value", "max_value"]
    list_filter = ["data_type", "monotonic"]
    search_fields = ["key", "label"]
    readonly_fields = ["id", "created", "modified"]
    fieldsets = [
        (None, {
            "fields": ["key", "label", "unit", "data_type", "description"],
        }),
        ("Value bounds", {
            "fields": ["min_value", "max_value", "monotonic"],
            "description": (
                "Optional bounds consumed by Spark's ingestion pipeline. "
                "Values outside [min_value, max_value] are rejected. "
                "Leave either bound null to skip that check. "
                "Monotonic flags cumulative counters that must not decrease."
            ),
        }),
        ("Identity", {
            "fields": ["id", "created", "modified"],
            "classes": ["collapse"],
        }),
    ]


@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ["code", "label", "icon", "vendor_model_count"]
    search_fields = ["code", "label", "description"]
    readonly_fields = ["id", "key", "vendor_model_count", "created", "modified"]
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 6, "cols": 60, "style": "font-family: monospace; width: 100%;"})},
    }
    fieldsets = [
        (None, {
            "fields": ["code", "label", "description", "icon"],
        }),
        ("Metrics profile (L2)", {
            "fields": ["metrics"],
            "description": (
                "List of {metric, tier} entries declaring which canonical "
                "L1 Metric keys this device type tracks, and at which "
                "display tier (primary / secondary / diagnostic). No sources "
                "or transforms here — those are decoder concerns on each "
                "VendorModel's ProcessorConfig.field_mappings."
            ),
        }),
        ("Identity", {
            "fields": ["id", "key", "vendor_model_count", "created", "modified"],
            "classes": ["collapse"],
        }),
    ]

    @admin.display(description="VendorModels")
    def vendor_model_count(self, obj):
        return obj.vendor_models.count()


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ["name", "slug", "device_count", "created"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ("name",)}

    @admin.display(description="Devices")
    def device_count(self, obj):
        return obj.device_types.count()


class ModbusConfigInline(admin.StackedInline):
    model = ModbusConfig
    extra = 0
    max_num = 1


class LoRaWANConfigInline(admin.StackedInline):
    model = LoRaWANConfig
    extra = 0
    max_num = 1
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


class WMBusConfigInline(admin.StackedInline):
    model = WMBusConfig
    extra = 0
    max_num = 1
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


class ControlConfigInline(admin.StackedInline):
    model = ControlConfig
    extra = 0
    max_num = 1
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


class ProcessorConfigInline(admin.StackedInline):
    model = ProcessorConfig
    extra = 0
    max_num = 1
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 12, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


@admin.register(VendorModel)
class VendorModelAdmin(admin.ModelAdmin):
    list_display = ["name", "vendor", "model_number", "device_type_fk", "technology", "offline_window_seconds", "created"]
    list_filter = ["device_type_fk", "technology", "vendor"]
    search_fields = ["name", "model_number", "vendor__name"]
    raw_id_fields = ["vendor"]
    inlines = [ModbusConfigInline, LoRaWANConfigInline, WMBusConfigInline, ControlConfigInline, ProcessorConfigInline]
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 5, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }
    fieldsets = [
        (None, {
            "fields": ["vendor", "model_number", "name", "description"],
        }),
        ("Type & technology", {
            "fields": ["device_type_fk", "device_type", "technology"],
            "description": (
                "Pick the canonical Device Type — the matching enum value is "
                "mirrored into ``device_type`` automatically for schema-v2 sync clients."
            ),
        }),
        ("Per-model behaviour", {
            "fields": ["offline_window_seconds"],
            "description": (
                "Override the DeviceType defaults for this specific meter. "
                "Field mappings live on ProcessorConfig.field_mappings — "
                "each entry maps a decoded ``source`` field to a canonical "
                "L1 ``metric`` key (with optional ``transform`` for unit "
                "conversion and ``tags`` for multi-channel disambiguation)."
            ),
        }),
        ("Identity", {
            "fields": ["key"],
            "classes": ["collapse"],
        }),
    ]


class RegisterDefinitionInline(admin.TabularInline):
    model = RegisterDefinition
    extra = 1


@admin.register(ModbusConfig)
class ModbusConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "function", "byte_order", "word_order", "register_count"]
    raw_id_fields = ["device_type"]
    inlines = [RegisterDefinitionInline]

    @admin.display(description="Registers")
    def register_count(self, obj):
        return obj.register_definitions.count()


@admin.register(RegisterDefinition)
class RegisterDefinitionAdmin(admin.ModelAdmin):
    list_display = ["field_name", "field_unit", "address", "data_type", "scale", "offset", "modbus_config"]
    list_filter = ["data_type"]
    search_fields = ["field_name"]
    raw_id_fields = ["modbus_config"]


@admin.register(LoRaWANConfig)
class LoRaWANConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "device_class", "downlink_f_port"]
    raw_id_fields = ["device_type"]
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


@admin.register(WMBusConfig)
class WMBusConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "manufacturer_code", "wmbus_version", "wmbus_device_type", "wmbusmeters_driver", "encryption_required", "is_mvt_default"]
    raw_id_fields = ["device_type"]
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


@admin.register(ControlConfig)
class ControlConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "controllable"]
    raw_id_fields = ["device_type"]
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


@admin.register(ProcessorConfig)
class ProcessorConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "decoder_type"]
    raw_id_fields = ["device_type"]
    formfield_overrides = {
        models.JSONField: {"widget": PrettyJSONWidget(attrs={"rows": 12, "cols": 80, "style": "font-family: monospace; width: 100%;"})},
    }


class LibraryVersionDeviceInline(admin.TabularInline):
    model = LibraryVersionDevice
    extra = 0
    raw_id_fields = ["device_type"]


@admin.register(LibraryVersion)
class LibraryVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "schema_version", "is_current", "released_at", "published_by"]
    list_filter = ["is_current"]
    inlines = [LibraryVersionDeviceInline]


@admin.register(GatewayAssignment)
class GatewayAssignmentAdmin(admin.ModelAdmin):
    list_display = ["serial_number", "spark_url", "assigned_at", "assigned_by"]
    search_fields = ["serial_number", "spark_url", "assigned_by"]


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "last_used_at", "created_by", "created"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    readonly_fields = ["key", "last_used_at"]
