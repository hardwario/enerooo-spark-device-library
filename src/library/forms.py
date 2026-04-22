"""Library forms."""

import re

from django import forms

from .models import (
    APIKey,
    ControlConfig,
    LoRaWANConfig,
    ModbusConfig,
    ProcessorConfig,
    RegisterDefinition,
    Vendor,
    VendorModel,
    WMBusConfig,
)


class PrettyJSONWidget(forms.Textarea):
    """Textarea widget that pretty-prints JSON content."""

    def format_value(self, value):
        import json

        if isinstance(value, str):
            try:
                value = json.dumps(json.loads(value), indent=2)
            except (json.JSONDecodeError, TypeError):
                pass
        elif value is not None:
            value = json.dumps(value, indent=2)
        return super().format_value(value)


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "slug"]


class VendorModelForm(forms.ModelForm):
    class Meta:
        model = VendorModel
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
        fields = ["device_class", "downlink_f_port", "codec_format", "payload_codec", "field_map"]
        widgets = {
            "payload_codec": forms.Textarea(attrs={
                "id": "script-textarea",
                "rows": 25,
                "style": "font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace; width: 100%; tab-size: 2;",
                "spellcheck": "false",
            }),
            "field_map": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"}),
        }


class WMBusConfigForm(forms.ModelForm):
    class Meta:
        model = WMBusConfig
        fields = [
            "manufacturer_code",
            "wmbus_version",
            "wmbus_device_type",
            "data_record_mapping",
            "encryption_required",
            "shared_encryption_key",
            "wmbusmeters_driver",
            "field_map",
            "is_mvt_default",
        ]
        widgets = {
            "data_record_mapping": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"}),
            "field_map": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"}),
            "shared_encryption_key": forms.TextInput(attrs={"placeholder": "e.g. BFBB1BB76A978E88F45EEE1260BF76E0", "style": "font-family: monospace;"}),
        }
        help_texts = {
            "shared_encryption_key": "32-character hex string (128-bit AES key).",
        }

    def clean_shared_encryption_key(self):
        key = self.cleaned_data.get("shared_encryption_key", "").strip().upper()
        if key and not re.fullmatch(r"[0-9A-F]{32}", key):
            raise forms.ValidationError("Must be exactly 32 hex characters (0-9, A-F).")
        return key


class ControlConfigForm(forms.ModelForm):
    class Meta:
        model = ControlConfig
        fields = ["controllable", "capabilities"]
        widgets = {
            "capabilities": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"}),
        }


class ProcessorConfigForm(forms.ModelForm):
    class Meta:
        model = ProcessorConfig
        fields = ["decoder_type"]


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
