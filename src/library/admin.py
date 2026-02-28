"""Library admin configuration."""

from django.contrib import admin

from .models import (
    APIKey,
    ControlConfig,
    DeviceType,
    LibraryVersion,
    LibraryVersionDevice,
    LoRaWANConfig,
    ModbusConfig,
    ProcessorConfig,
    RegisterDefinition,
    Vendor,
    WMBusConfig,
)


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


class WMBusConfigInline(admin.StackedInline):
    model = WMBusConfig
    extra = 0
    max_num = 1


class ControlConfigInline(admin.StackedInline):
    model = ControlConfig
    extra = 0
    max_num = 1


class ProcessorConfigInline(admin.StackedInline):
    model = ProcessorConfig
    extra = 0
    max_num = 1


@admin.register(DeviceType)
class DeviceTypeAdmin(admin.ModelAdmin):
    list_display = ["name", "vendor", "model_number", "device_type", "technology", "created"]
    list_filter = ["device_type", "technology", "vendor"]
    search_fields = ["name", "model_number", "vendor__name"]
    raw_id_fields = ["vendor"]
    inlines = [ModbusConfigInline, LoRaWANConfigInline, WMBusConfigInline, ControlConfigInline, ProcessorConfigInline]


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


@admin.register(WMBusConfig)
class WMBusConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "manufacturer_code", "wmbus_device_type", "encryption_required"]
    raw_id_fields = ["device_type"]


@admin.register(ControlConfig)
class ControlConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "controllable"]
    raw_id_fields = ["device_type"]


@admin.register(ProcessorConfig)
class ProcessorConfigAdmin(admin.ModelAdmin):
    list_display = ["device_type", "decoder_type"]
    raw_id_fields = ["device_type"]


class LibraryVersionDeviceInline(admin.TabularInline):
    model = LibraryVersionDevice
    extra = 0
    raw_id_fields = ["device_type"]


@admin.register(LibraryVersion)
class LibraryVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "schema_version", "is_current", "released_at", "published_by"]
    list_filter = ["is_current"]
    inlines = [LibraryVersionDeviceInline]


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ["name", "is_active", "last_used_at", "created_by", "created"]
    list_filter = ["is_active"]
    search_fields = ["name"]
    readonly_fields = ["key", "last_used_at"]
