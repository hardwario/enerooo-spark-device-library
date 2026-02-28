"""API serializers for the device library."""

from rest_framework import serializers

from library.models import (
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


# === Sync API serializers (read-only, nested) ===


class RegisterDefinitionSerializer(serializers.ModelSerializer):
    field = serializers.SerializerMethodField()

    class Meta:
        model = RegisterDefinition
        fields = ["field", "scale", "offset", "address", "data_type"]

    def get_field(self, obj):
        return {"name": obj.field_name, "unit": obj.field_unit}


class ModbusConfigSerializer(serializers.ModelSerializer):
    register_definitions = RegisterDefinitionSerializer(many=True, read_only=True)

    class Meta:
        model = ModbusConfig
        fields = ["function", "byte_order", "word_order", "register_definitions"]


class LoRaWANConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = LoRaWANConfig
        fields = ["device_class", "downlink_f_port"]


class WMBusConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = WMBusConfig
        fields = [
            "manufacturer_code",
            "wmbus_device_type",
            "data_record_mapping",
            "encryption_required",
            "shared_encryption_key",
        ]


class ControlConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ControlConfig
        fields = ["controllable", "capabilities"]


class ProcessorConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessorConfig
        fields = ["decoder_type"]


class DeviceTechnologyConfigSerializer(serializers.Serializer):
    """Serializes technology_config matching the YAML schema."""

    technology = serializers.CharField()

    def to_representation(self, device):
        data = {"technology": device.technology}

        if device.technology == "modbus":
            try:
                modbus = device.modbus_config
                if modbus.function:
                    data["function"] = modbus.function
                if modbus.byte_order:
                    data["byte_order"] = modbus.byte_order
                if modbus.word_order:
                    data["word_order"] = modbus.word_order
                regs = RegisterDefinitionSerializer(modbus.register_definitions.all(), many=True).data
                if regs:
                    data["register_definitions"] = regs
            except ModbusConfig.DoesNotExist:
                pass

        elif device.technology == "lorawan":
            try:
                lorawan = device.lorawan_config
                if lorawan.device_class:
                    data["device_class"] = lorawan.device_class
                if lorawan.downlink_f_port is not None:
                    data["downlink_f_port"] = lorawan.downlink_f_port
            except LoRaWANConfig.DoesNotExist:
                pass

        elif device.technology == "wmbus":
            try:
                wmbus = device.wmbus_config
                data["manufacturer_code"] = wmbus.manufacturer_code
                data["wmbus_device_type"] = wmbus.wmbus_device_type
                data["data_record_mapping"] = wmbus.data_record_mapping
                data["encryption_required"] = wmbus.encryption_required
                if wmbus.shared_encryption_key:
                    data["shared_encryption_key"] = wmbus.shared_encryption_key
            except WMBusConfig.DoesNotExist:
                pass

        return data


class DeviceTypeListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for device lists."""

    vendor_name = serializers.CharField(source="vendor.name", read_only=True)

    class Meta:
        model = DeviceType
        fields = ["id", "vendor_name", "model_number", "name", "device_type", "technology"]


class DeviceTypeDetailSerializer(serializers.ModelSerializer):
    """Full serializer matching the YAML schema structure."""

    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    technology_config = DeviceTechnologyConfigSerializer(source="*", read_only=True)
    control_config = serializers.SerializerMethodField()
    processor_config = serializers.SerializerMethodField()

    class Meta:
        model = DeviceType
        fields = [
            "id",
            "vendor_name",
            "model_number",
            "name",
            "device_type",
            "description",
            "technology_config",
            "control_config",
            "processor_config",
        ]

    def get_control_config(self, obj):
        try:
            return ControlConfigSerializer(obj.control_config).data
        except ControlConfig.DoesNotExist:
            return {}

    def get_processor_config(self, obj):
        try:
            return ProcessorConfigSerializer(obj.processor_config).data
        except ProcessorConfig.DoesNotExist:
            return {}


class VendorSerializer(serializers.ModelSerializer):
    device_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Vendor
        fields = ["id", "name", "slug", "device_count"]


class VendorWithDevicesSerializer(serializers.ModelSerializer):
    """Vendor with nested device types for sync endpoint."""

    device_types = DeviceTypeDetailSerializer(many=True, read_only=True)

    class Meta:
        model = Vendor
        fields = ["name", "slug", "device_types"]


# === Manifest ===


class ManifestSerializer(serializers.Serializer):
    version = serializers.CharField()
    schema_version = serializers.IntegerField()
    vendor_count = serializers.IntegerField()
    device_count = serializers.IntegerField()


# === Version serializers ===


class LibraryVersionDeviceSerializer(serializers.ModelSerializer):
    device_name = serializers.CharField(source="device_type.name", read_only=True)

    class Meta:
        model = LibraryVersionDevice
        fields = ["device_name", "change_type"]


class LibraryVersionSerializer(serializers.ModelSerializer):
    device_changes = LibraryVersionDeviceSerializer(many=True, read_only=True)

    class Meta:
        model = LibraryVersion
        fields = ["id", "version", "schema_version", "released_at", "notes", "is_current", "device_changes"]


# === Admin API serializers (CRUD) ===


class VendorAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vendor
        fields = ["id", "name", "slug", "created", "modified"]
        read_only_fields = ["id", "created", "modified"]


class DeviceTypeAdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeviceType
        fields = ["id", "vendor", "model_number", "name", "device_type", "technology", "description", "created", "modified"]
        read_only_fields = ["id", "created", "modified"]


class APIKeySerializer(serializers.ModelSerializer):
    class Meta:
        model = APIKey
        fields = ["id", "name", "key", "is_active", "last_used_at", "created_by", "created"]
        read_only_fields = ["id", "key", "last_used_at", "created_by", "created"]
