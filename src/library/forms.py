"""Library forms."""

import re

from django import forms

from .models import (
    APIKey,
    ControlConfig,
    LoRaWANConfig,
    Metric,
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


class FieldMappingsWidget(forms.Textarea):
    """Tabular editor for ``ProcessorConfig.field_mappings``.

    Each row: ``source`` text, ``metric`` autocomplete (free-form — typing a
    new key triggers L1 auto-create on save), optional ``scale`` and
    ``offset`` number inputs, optional ``tags`` JSON. Hidden textarea keeps
    Django's JSONField serialization unchanged.
    """

    template_name = "library/widgets/field_mappings.html"

    def format_value(self, value):
        import json

        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value else []
            except json.JSONDecodeError:
                parsed = []
        elif value is None:
            parsed = []
        else:
            parsed = value
        return json.dumps(parsed, indent=2, ensure_ascii=False)

    def get_context(self, name, value, attrs):
        import json

        from .models import Metric

        ctx = super().get_context(name, value, attrs)
        available = list(Metric.objects.values("key", "label", "unit").order_by("key"))
        ctx["widget"]["available_metrics_json"] = json.dumps(available)
        return ctx


class MetricsProfileWidget(forms.Textarea):
    """Tabular editor for DeviceType.metrics — one row per (metric, tier).

    Renders a hidden textarea (Django form serialization stays JSON-based)
    plus an interactive table with a select for ``metric`` (autocompleted
    from the L1 ``Metric`` catalogue) and a dropdown for ``tier``. A small
    inline script syncs row edits back to the textarea so submit just works.
    """

    template_name = "library/widgets/metrics_profile.html"

    def format_value(self, value):
        import json

        if isinstance(value, str):
            try:
                parsed = json.loads(value) if value else []
            except json.JSONDecodeError:
                parsed = []
        elif value is None:
            parsed = []
        else:
            parsed = value
        return json.dumps(parsed, indent=2, ensure_ascii=False)

    def get_context(self, name, value, attrs):
        import json

        from .models import Metric

        ctx = super().get_context(name, value, attrs)
        available = list(Metric.objects.values("key", "label").order_by("key"))
        ctx["widget"]["available_metrics_json"] = json.dumps(available)
        return ctx


class MetricForm(forms.ModelForm):
    class Meta:
        model = Metric
        fields = ["key", "label", "unit", "data_type", "description"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "key": forms.TextInput(attrs={"placeholder": "e.g. heat:total_energy"}),
            "unit": forms.TextInput(attrs={"placeholder": "e.g. kWh"}),
        }
        help_texts = {
            "key": "Namespaced canonical key, format '<namespace>:<name>' (e.g. heat:total_energy, device:battery).",
            "unit": "Canonical unit symbol (kWh, m³, dBm, …). Empty for dimensionless metrics.",
        }

    def clean_key(self):
        key = (self.cleaned_data.get("key") or "").strip()
        if not key:
            raise forms.ValidationError("Key is required.")
        if ":" not in key:
            raise forms.ValidationError("Key must be namespaced as '<namespace>:<name>' (e.g. heat:total_energy).")
        namespace, _, name = key.partition(":")
        if not namespace or not name:
            raise forms.ValidationError("Both namespace and name parts must be non-empty.")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", namespace):
            raise forms.ValidationError("Namespace must be lowercase, start with a letter, and contain only letters, digits, underscores.")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise forms.ValidationError("Name must be lowercase, start with a letter, and contain only letters, digits, underscores.")
        return key


class VendorForm(forms.ModelForm):
    class Meta:
        model = Vendor
        fields = ["name", "slug"]


class VendorModelForm(forms.ModelForm):
    class Meta:
        model = VendorModel
        fields = [
            "vendor",
            "model_number",
            "name",
            "device_type",
            "device_type_fk",
            "technology",
            "description",
            "offline_window_seconds",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
        }


class DeviceTypeForm(forms.ModelForm):
    class Meta:
        from .models import DeviceType
        model = DeviceType
        fields = [
            "code",
            "label",
            "description",
            "icon",
            "metrics",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "metrics": MetricsProfileWidget(),
        }

    def clean_metrics(self):
        val = self.cleaned_data.get("metrics")
        return val if val is not None else []


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

    def clean_field_map(self):
        val = self.cleaned_data.get("field_map")
        return val if val is not None else {}


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

    def clean_data_record_mapping(self):
        val = self.cleaned_data.get("data_record_mapping")
        return val if val is not None else []

    def clean_field_map(self):
        val = self.cleaned_data.get("field_map")
        return val if val is not None else {}


class ControlConfigForm(forms.ModelForm):
    class Meta:
        model = ControlConfig
        fields = ["controllable", "capabilities"]
        widgets = {
            "capabilities": PrettyJSONWidget(attrs={"rows": 20, "cols": 80, "style": "font-family: monospace; width: 100%;"}),
        }

    def clean_capabilities(self):
        val = self.cleaned_data.get("capabilities")
        return val if val is not None else {}


class ProcessorConfigForm(forms.ModelForm):
    class Meta:
        model = ProcessorConfig
        # ``decoder_type`` is auto-derived from VendorModel.technology in
        # ProcessorConfig.save() (wmbus → wmbus_field_map, lorawan → js_codec
        # or lorawan_field_map based on payload_codec presence). Hidden from
        # the form to keep the editor minimal.
        fields = ["field_mappings", "extra_config"]
        widgets = {
            "extra_config": PrettyJSONWidget(attrs={"rows": 10, "cols": 80, "style": "font-family: monospace; width: 100%;"}),
            "field_mappings": FieldMappingsWidget(),
        }
        # Model help_text for field_mappings is long. The widget renders its
        # own collapsible help, so suppress the duplicate here.
        help_texts = {
            "field_mappings": "",
        }

    def clean_extra_config(self):
        # JSONField.to_python returns None for an empty textarea, but the DB
        # column is NOT NULL with default={}. Coerce empty input to {}.
        val = self.cleaned_data.get("extra_config")
        return val if val is not None else {}

    def clean_field_mappings(self):
        val = self.cleaned_data.get("field_mappings")
        return val if val is not None else []


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
