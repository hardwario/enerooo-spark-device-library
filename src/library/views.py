"""Library views for the web UI."""

import json

import yaml
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, OuterRef, Q, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from auditlog.helpers import log_action
from core.models import User
from core.permissions import RoleRequiredMixin

from .exporters import export_to_yaml
from .forms import APIKeyForm, DeviceTypeForm, RegisterDefinitionForm, VendorForm, YAMLImportForm
from .history import diff_snapshots, record_history, snapshot_device
from .importers import import_from_yaml
from .models import (
    APIKey,
    DeviceHistory,
    DeviceType,
    LibraryVersion,
    LibraryVersionDevice,
    RegisterDefinition,
    Vendor,
)


# === Dashboard ===


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "library/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vendor_count"] = Vendor.objects.count()
        ctx["device_count"] = DeviceType.objects.count()
        current = LibraryVersion.objects.filter(is_current=True).first()
        ctx["current_version"] = f"v{current.version}" if current else None
        ctx["apikey_count"] = APIKey.objects.filter(is_active=True).count()
        ctx["tech_breakdown"] = (
            DeviceType.objects.values("technology").annotate(count=Count("id")).order_by("technology")
        )
        ctx["type_breakdown"] = (
            DeviceType.objects.values("device_type").annotate(count=Count("id")).order_by("device_type")
        )
        return ctx


# === Vendors ===


class VendorListView(LoginRequiredMixin, ListView):
    template_name = "library/vendor_list.html"
    context_object_name = "vendors"
    ALLOWED_SORT_FIELDS = {"name", "slug", "modbus_count", "lorawan_count", "wmbus_count", "device_count"}

    def get_queryset(self):
        qs = Vendor.objects.annotate(
            device_count=Count("device_types"),
            modbus_count=Count("device_types", filter=Q(device_types__technology="modbus")),
            lorawan_count=Count("device_types", filter=Q(device_types__technology="lorawan")),
            wmbus_count=Count("device_types", filter=Q(device_types__technology="wmbus")),
        )
        sort = self.request.GET.get("sort", "name")
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        if field not in self.ALLOWED_SORT_FIELDS:
            field, descending = "name", False
        order = f"-{field}" if descending else field
        return qs.order_by(order)


class VendorCreateView(LoginRequiredMixin, CreateView):
    model = Vendor
    form_class = VendorForm
    template_name = "library/vendor_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, "created", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:vendor-detail", kwargs={"slug": self.object.slug})


class VendorDeleteView(LoginRequiredMixin, View):
    def post(self, request, slug):
        vendor = get_object_or_404(Vendor, slug=slug)
        if vendor.device_types.exists():
            messages.error(request, f"Cannot delete {vendor.name} — it still has {vendor.device_types.count()} device(s). Remove them first.")
            return redirect("library:vendor-detail", slug=vendor.slug)
        name = vendor.name
        log_action(request, "deleted", vendor)
        vendor.delete()
        messages.success(request, f"Vendor \"{name}\" has been deleted.")
        return redirect("library:vendor-list")


class VendorDetailView(LoginRequiredMixin, DetailView):
    template_name = "library/vendor_detail.html"
    model = Vendor
    context_object_name = "vendor"
    slug_field = "slug"
    slug_url_kwarg = "slug"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["devices"] = self.object.device_types.select_related("vendor").all()
        return ctx


# === Devices ===


class DeviceTypeListView(LoginRequiredMixin, ListView):
    template_name = "library/devicetype_list.html"
    context_object_name = "devices"
    paginate_by = 50
    ALLOWED_SORT_FIELDS = {
        "vendor": "vendor__name",
        "model_number": "model_number",
        "name": "name",
        "device_type": "device_type",
        "technology": "technology",
    }

    def get_queryset(self):
        latest_version = (
            DeviceHistory.objects.filter(device=OuterRef("pk"))
            .order_by("-version")
            .values("version")[:1]
        )
        qs = DeviceType.objects.select_related("vendor").annotate(
            current_version=Subquery(latest_version),
        )
        vendor = self.request.GET.get("vendor")
        technology = self.request.GET.get("technology")
        device_type = self.request.GET.get("device_type")

        if vendor:
            qs = qs.filter(vendor__slug=vendor)
        if technology:
            qs = qs.filter(technology=technology)
        if device_type:
            qs = qs.filter(device_type=device_type)

        sort = self.request.GET.get("sort", "vendor")
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        db_field = self.ALLOWED_SORT_FIELDS.get(field)
        if not db_field:
            db_field, descending = "vendor__name", False
        order = f"-{db_field}" if descending else db_field
        return qs.order_by(order, "model_number")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vendors"] = Vendor.objects.all()
        ctx["device_type_choices"] = DeviceType.DeviceCategory.choices
        ctx["total_count"] = DeviceType.objects.count()
        ctx["filtered_count"] = self.get_queryset().count()
        return ctx


class DeviceTypeDetailView(LoginRequiredMixin, DetailView):
    template_name = "library/devicetype_detail.html"
    model = DeviceType
    context_object_name = "device"

    def get_queryset(self):
        return DeviceType.objects.select_related(
            "vendor",
            "modbus_config",
            "lorawan_config",
            "wmbus_config",
            "control_config",
            "processor_config",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        device = self.object

        # Technology config
        try:
            ctx["modbus_config"] = device.modbus_config
        except Exception:
            ctx["modbus_config"] = None

        try:
            ctx["lorawan_config"] = device.lorawan_config
        except Exception:
            ctx["lorawan_config"] = None

        try:
            ctx["wmbus_config"] = device.wmbus_config
        except Exception:
            ctx["wmbus_config"] = None

        try:
            ctx["control_config"] = device.control_config
        except Exception:
            ctx["control_config"] = None

        try:
            ctx["processor_config"] = device.processor_config
        except Exception:
            ctx["processor_config"] = None

        # Registers
        if ctx["modbus_config"]:
            ctx["registers"] = ctx["modbus_config"].register_definitions.all()
        else:
            ctx["registers"] = []

        # History
        ctx["history"] = device.history.select_related("user").all()[:20]

        return ctx


class DeviceTypeCreateView(LoginRequiredMixin, CreateView):
    model = DeviceType
    form_class = DeviceTypeForm
    template_name = "library/devicetype_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        record_history(self.object, DeviceHistory.Action.CREATED, self.request.user)
        log_action(self.request, "created", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.pk})


class DeviceTypeUpdateView(LoginRequiredMixin, UpdateView):
    model = DeviceType
    form_class = DeviceTypeForm
    template_name = "library/devicetype_form.html"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        self._old_snapshot = snapshot_device(obj)
        return obj

    def form_valid(self, form):
        response = super().form_valid(form)
        record_history(self.object, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.pk})


class DeviceTypeDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        device = get_object_or_404(DeviceType, pk=pk)
        name = f"{device.vendor.name} {device.model_number}"
        record_history(device, DeviceHistory.Action.DELETED, request.user)
        log_action(request, "deleted", device)
        device.delete()
        messages.success(request, f"Device \"{name}\" has been deleted.")
        return redirect("library:device-list")


# === Registers ===


class RegisterListView(LoginRequiredMixin, ListView):
    """Redirect to device detail (registers shown inline)."""

    def get(self, request, device_pk):
        return redirect("library:device-detail", pk=device_pk)


class RegisterCreateView(LoginRequiredMixin, CreateView):
    model = RegisterDefinition
    form_class = RegisterDefinitionForm
    template_name = "library/register_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = get_object_or_404(DeviceType, pk=self.kwargs["device_pk"])
        return ctx

    def form_valid(self, form):
        device = get_object_or_404(DeviceType, pk=self.kwargs["device_pk"])
        old_snapshot = snapshot_device(device)
        # Ensure modbus config exists
        from .models import ModbusConfig

        modbus_config, _ = ModbusConfig.objects.get_or_create(device_type=device)
        form.instance.modbus_config = modbus_config
        response = super().form_valid(form)
        record_history(device, DeviceHistory.Action.UPDATED, self.request.user, old_snapshot)
        log_action(self.request, "created", form.instance, details=f"Register added to {device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.kwargs["device_pk"]})


class RegisterUpdateView(LoginRequiredMixin, UpdateView):
    model = RegisterDefinition
    form_class = RegisterDefinitionForm
    template_name = "library/register_form.html"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        device = obj.modbus_config.device_type
        self._device = device
        self._old_snapshot = snapshot_device(device)
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self.object.modbus_config.device_type
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        record_history(self._device, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", form.instance, details=f"Register updated on {self._device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.modbus_config.device_type.pk})


class RegisterDeleteView(LoginRequiredMixin, DeleteView):
    model = RegisterDefinition
    template_name = "library/register_confirm_delete.html"

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        device = self.object.modbus_config.device_type
        old_snapshot = snapshot_device(device)
        reg_name = self.object.field_name
        self.object.delete()
        record_history(device, DeviceHistory.Action.UPDATED, request.user, old_snapshot)
        log_action(request, "deleted", self.object, details=f"Register '{reg_name}' removed from {device}")
        return redirect("library:device-detail", pk=device.pk)


# === Device History ===


class DeviceHistoryDiffView(LoginRequiredMixin, TemplateView):
    template_name = "library/devicetype_history_diff.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        device = get_object_or_404(DeviceType, pk=self.kwargs["pk"])
        ctx["device"] = device

        from_version = int(self.request.GET.get("from", 0))
        to_version = int(self.request.GET.get("to", 0))

        from_entry = get_object_or_404(DeviceHistory, device=device, version=from_version)
        to_entry = get_object_or_404(DeviceHistory, device=device, version=to_version)

        ctx["from_entry"] = from_entry
        ctx["to_entry"] = to_entry
        ctx["diff"] = diff_snapshots(from_entry.snapshot, to_entry.snapshot)

        return ctx


# === Import / Export ===


class ImportView(LoginRequiredMixin, TemplateView):
    template_name = "library/import.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "form" not in ctx:
            ctx["form"] = YAMLImportForm(initial={
                "devices_path": "/app/devices/",
                "manifest_path": "/app/manifest.yaml",
            })
        return ctx

    def post(self, request):
        form = YAMLImportForm(request.POST)
        if form.is_valid():
            try:
                stats = import_from_yaml(
                    devices_path=form.cleaned_data["devices_path"],
                    manifest_path=form.cleaned_data["manifest_path"],
                    clear=form.cleaned_data["clear_existing"],
                )
                return self.render_to_response(self.get_context_data(form=form, stats=stats))
            except Exception as e:
                messages.error(request, f"Import failed: {e}")

        return self.render_to_response(self.get_context_data(form=form))


class ExportView(LoginRequiredMixin, TemplateView):
    template_name = "library/export.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["default_output_dir"] = "/app/export/devices/"
        return ctx

    def post(self, request):
        output_dir = request.POST.get("output_dir", "/app/export/devices/")
        try:
            stats = export_to_yaml(output_dir=output_dir)
            return self.render_to_response(self.get_context_data(stats=stats, output_dir=output_dir))
        except Exception as e:
            messages.error(request, f"Export failed: {e}")
            return self.render_to_response(self.get_context_data())


# === Versions ===


class VersionListView(LoginRequiredMixin, ListView):
    template_name = "library/version_list.html"
    context_object_name = "versions"
    queryset = LibraryVersion.objects.all()


class VersionDetailView(LoginRequiredMixin, DetailView):
    template_name = "library/version_detail.html"
    model = LibraryVersion
    context_object_name = "version"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        entries = self.object.device_changes.select_related("device_type", "device_type__vendor").all()
        ctx["manifest"] = entries
        ctx["device_count"] = entries.exclude(change_type=LibraryVersionDevice.ChangeType.REMOVED).count()
        ctx["changed_count"] = entries.exclude(change_type=LibraryVersionDevice.ChangeType.UNCHANGED).count()
        return ctx


class VersionCreateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request):
        # Auto-compute next version number
        max_version = LibraryVersion.objects.aggregate(v=Max("version"))["v"] or 0
        new_version = max_version + 1

        # Backfill: ensure every DeviceType has at least one DeviceHistory entry
        devices_without_history = DeviceType.objects.filter(history__isnull=True)
        for device in devices_without_history:
            record_history(device, DeviceHistory.Action.CREATED, user=None)

        # Create the new library version
        lib_version = LibraryVersion.objects.create(
            version=new_version,
            published_by=request.user,
            is_current=True,
        )

        # Build previous version's manifest for comparison
        prev_version = (
            LibraryVersion.objects.filter(version__lt=new_version).order_by("-version").first()
        )
        prev_manifest = {}
        if prev_version:
            for entry in prev_version.device_changes.all():
                if entry.device_type_id and entry.change_type != LibraryVersionDevice.ChangeType.REMOVED:
                    prev_manifest[entry.device_type_id] = entry.device_version

        # Snapshot all current devices
        current_device_ids = set()
        for device in DeviceType.objects.select_related("vendor"):
            current_device_ids.add(device.pk)
            # Get latest DeviceHistory version for this device
            latest_version = (
                DeviceHistory.objects.filter(device=device)
                .order_by("-version")
                .values_list("version", flat=True)
                .first()
            ) or 1

            # Determine change_type
            if device.pk in prev_manifest:
                if prev_manifest[device.pk] == latest_version:
                    change_type = LibraryVersionDevice.ChangeType.UNCHANGED
                else:
                    change_type = LibraryVersionDevice.ChangeType.MODIFIED
            else:
                change_type = LibraryVersionDevice.ChangeType.ADDED

            LibraryVersionDevice.objects.create(
                library_version=lib_version,
                device_type=device,
                device_version=latest_version,
                device_label=str(device),
                change_type=change_type,
            )

        # Detect removed devices (in previous but not in current)
        if prev_version:
            for prev_device_id, prev_device_version in prev_manifest.items():
                if prev_device_id not in current_device_ids:
                    # Get label from previous manifest entry
                    prev_entry = prev_version.device_changes.filter(device_type_id=prev_device_id).first()
                    label = prev_entry.device_label if prev_entry else "Deleted device"
                    LibraryVersionDevice.objects.create(
                        library_version=lib_version,
                        device_type=None,
                        device_version=prev_device_version,
                        device_label=label,
                        change_type=LibraryVersionDevice.ChangeType.REMOVED,
                    )

        messages.success(request, f"Library version v{new_version} created.")
        return redirect("library:version-detail", pk=lib_version.pk)


class VersionExportView(LoginRequiredMixin, View):
    """Export a library version as JSON or YAML download."""

    def get(self, request, pk):
        lib_version = get_object_or_404(LibraryVersion, pk=pk)
        fmt = request.GET.get("format", "json")

        entries = lib_version.device_changes.select_related("device_type").exclude(
            change_type=LibraryVersionDevice.ChangeType.REMOVED,
        )

        # Batch-fetch all relevant DeviceHistory snapshots
        history_lookup = {}
        for entry in entries:
            if entry.device_type_id:
                history_entry = (
                    DeviceHistory.objects.filter(
                        device_id=entry.device_type_id,
                        version=entry.device_version,
                    )
                    .values_list("snapshot", flat=True)
                    .first()
                )
                if history_entry:
                    history_lookup[entry.device_type_id] = history_entry

        # Group devices by vendor and convert snapshots to schema format
        vendors = {}
        for entry in entries:
            snapshot = history_lookup.get(entry.device_type_id)
            if not snapshot:
                continue
            vendor_name = snapshot.get("vendor", "Unknown")
            if vendor_name not in vendors:
                vendors[vendor_name] = []
            vendors[vendor_name].append(_snapshot_to_schema(snapshot))

        # Build final document
        vendor_list = []
        for vendor_name in sorted(vendors):
            vendor_list.append({
                "name": vendor_name,
                "device_types": vendors[vendor_name],
            })

        document = {
            "version": lib_version.version,
            "schema_version": lib_version.schema_version,
            "vendors": vendor_list,
        }

        if fmt == "yaml":
            content = yaml.dump(document, default_flow_style=False, sort_keys=False, allow_unicode=True)
            response = HttpResponse(content, content_type="application/x-yaml")
            response["Content-Disposition"] = f'attachment; filename="library-v{lib_version.version}.yaml"'
        else:
            content = json.dumps(document, indent=2, ensure_ascii=False)
            response = HttpResponse(content, content_type="application/json")
            response["Content-Disposition"] = f'attachment; filename="library-v{lib_version.version}.json"'

        return response


def _snapshot_to_schema(snapshot: dict) -> dict:
    """Convert a DeviceHistory snapshot dict to the YAML device schema format."""
    technology = snapshot.get("technology", "")

    tech_config = {"technology": technology}
    if technology == "modbus":
        mc = snapshot.get("modbus_config", {})
        if mc.get("function"):
            tech_config["function"] = mc["function"]
        if mc.get("byte_order"):
            tech_config["byte_order"] = mc["byte_order"]
        if mc.get("word_order"):
            tech_config["word_order"] = mc["word_order"]
        registers = snapshot.get("registers", [])
        if registers:
            tech_config["register_definitions"] = [
                {
                    "field": {"name": r["field_name"], "unit": r.get("field_unit", "")},
                    "scale": r.get("scale", 1.0),
                    "offset": r.get("offset", 0.0),
                    "address": r["address"],
                    "data_type": r.get("data_type", "uint16"),
                }
                for r in registers
            ]
    elif technology == "lorawan":
        lc = snapshot.get("lorawan_config", {})
        if lc.get("device_class"):
            tech_config["device_class"] = lc["device_class"]
        if lc.get("downlink_f_port") is not None:
            tech_config["downlink_f_port"] = lc["downlink_f_port"]
    elif technology == "wmbus":
        wc = snapshot.get("wmbus_config", {})
        tech_config["manufacturer_code"] = wc.get("manufacturer_code", "")
        tech_config["wmbus_device_type"] = wc.get("wmbus_device_type")
        tech_config["data_record_mapping"] = wc.get("data_record_mapping", [])
        tech_config["encryption_required"] = wc.get("encryption_required", False)
        if wc.get("shared_encryption_key"):
            tech_config["shared_encryption_key"] = wc["shared_encryption_key"]

    device = {
        "vendor_name": snapshot.get("vendor", ""),
        "model_number": snapshot.get("model_number", ""),
        "name": snapshot.get("name", ""),
        "device_type": snapshot.get("device_type", ""),
        "description": snapshot.get("description", ""),
        "technology_config": tech_config,
    }

    ctrl = snapshot.get("control_config", {})
    if ctrl and (ctrl.get("controllable") or ctrl.get("capabilities")):
        device["control_config"] = ctrl

    proc = snapshot.get("processor_config", {})
    if proc and proc.get("decoder_type"):
        device["processor_config"] = proc

    return device


# === API Keys ===


class APIKeyListView(LoginRequiredMixin, ListView):
    template_name = "library/apikey_list.html"
    context_object_name = "apikeys"
    queryset = APIKey.objects.all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["new_key"] = self.request.session.pop("new_api_key", None)
        return ctx


class APIKeyCreateView(LoginRequiredMixin, CreateView):
    model = APIKey
    form_class = APIKeyForm
    template_name = "library/apikey_form.html"

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        response = super().form_valid(form)
        self.request.session["new_api_key"] = self.object.key
        return response

    def get_success_url(self):
        return reverse_lazy("library:apikey-list")


class APIKeyRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        apikey.is_active = False
        apikey.save(update_fields=["is_active"])
        messages.success(request, f"API key '{apikey.name}' has been revoked.")
        return redirect("library:apikey-list")
