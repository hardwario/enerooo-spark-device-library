"""Library forms."""

from django import forms

from .models import (
    APIKey,
    ControlConfig,
    DeviceType,
    LibraryVersion,
    LoRaWANConfig,
    ModbusConfig,
    ProcessorConfig,
    RegisterDefinition,
    Vendor,
    WMBusConfig,
)


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "slug"]


class DeviceTypeForm(forms.ModelForm):
    class Meta:
        model = DeviceType
        fields = ["vendor", "model_number", "name", "device_type", "technology", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class ModbusConfigForm(forms.ModelForm):
    class Meta:
        model = ModbusConfig
        fields = ["function", "byte_order", "word_order"]


class RegisterDefinitionForm(forms.ModelForm):
    class Meta:
        model = RegisterDefinition
        fields = ["field_name", "field_unit", "address", "data_type", "scale", "offset"]


class LoRaWANConfigForm(forms.ModelForm):
    class Meta:
        model = LoRaWANConfig
        fields = ["device_class", "downlink_f_port"]


class WMBusConfigForm(forms.ModelForm):
    class Meta:
        model = WMBusConfig
        fields = [
            "manufacturer_code",
            "wmbus_device_type",
            "data_record_mapping",
            "encryption_required",
            "shared_encryption_key",
        ]


class ControlConfigForm(forms.ModelForm):
    class Meta:
        model = ControlConfig
        fields = ["controllable", "capabilities"]


class ProcessorConfigForm(forms.ModelForm):
    class Meta:
        model = ProcessorConfig
        fields = ["decoder_type"]


class LibraryVersionForm(forms.ModelForm):
    class Meta:
        model = LibraryVersion
        fields = ["version", "schema_version", "notes"]


class APIKeyForm(forms.ModelForm):
    class Meta:
        model = APIKey
        fields = ["name"]


class YAMLImportForm(forms.Form):
    """Form for importing device definitions from YAML files."""

    devices_path = forms.CharField(
        label="Devices directory path",
        help_text="Path to the devices/ directory containing YAML files",
    )
    manifest_path = forms.CharField(
        label="Manifest file path",
        help_text="Path to manifest.yaml",
    )
    clear_existing = forms.BooleanField(
        required=False,
        label="Clear existing data",
        help_text="Delete all existing vendors and devices before importing",
    )
