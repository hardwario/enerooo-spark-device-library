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
from auditlog.models import AuditLog
from core.models import User
from core.permissions import RoleRequiredMixin, SuperuserRequiredMixin

from .exporters import export_to_yaml, snapshot_to_schema
from .forms import APIKeyForm, RegisterDefinitionForm, VendorForm, VendorModelForm, YAMLImportForm
from .history import diff_snapshots, record_history, snapshot_device
from .importers import import_from_yaml
from .models import (
    APIKey,
    DeviceHistory,
    LibraryVersion,
    LibraryVersionDevice,
    RegisterDefinition,
    Vendor,
    VendorModel,
)


# === Dashboard ===


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "library/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vendor_count"] = Vendor.objects.count()
        ctx["model_count"] = VendorModel.objects.count()
        current = LibraryVersion.objects.filter(is_current=True).first()
        ctx["current_version"] = f"v{current.version}" if current else None
        ctx["apikey_count"] = APIKey.objects.filter(is_active=True).count()
        ctx["tech_breakdown"] = (
            VendorModel.objects.values("technology").annotate(count=Count("id")).order_by("technology")
        )
        ctx["type_breakdown"] = (
            VendorModel.objects.values("device_type").annotate(count=Count("id")).order_by("device_type")
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
            messages.error(request, f"Cannot delete {vendor.name} — it still has {vendor.device_types.count()} model(s). Remove them first.")
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
        ctx["models"] = self.object.device_types.select_related("vendor").all()
        return ctx


# === Devices ===


class VendorModelListView(LoginRequiredMixin, ListView):
    template_name = "library/devicetype_list.html"
    context_object_name = "models"
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
        qs = VendorModel.objects.select_related("vendor").annotate(
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
        ctx["device_type_choices"] = VendorModel.DeviceCategory.choices
        ctx["total_count"] = VendorModel.objects.count()
        ctx["filtered_count"] = self.get_queryset().count()
        return ctx


class VendorModelDetailView(LoginRequiredMixin, DetailView):
    template_name = "library/devicetype_detail.html"
    model = VendorModel
    context_object_name = "device"

    def get_queryset(self):
        return VendorModel.objects.select_related(
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


class VendorModelCreateView(LoginRequiredMixin, CreateView):
    model = VendorModel
    form_class = VendorModelForm
    template_name = "library/devicetype_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        record_history(self.object, DeviceHistory.Action.CREATED, self.request.user)
        log_action(self.request, "created", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:model-detail", kwargs={"pk": self.object.pk})


class VendorModelUpdateView(LoginRequiredMixin, UpdateView):
    model = VendorModel
    form_class = VendorModelForm
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
        return reverse_lazy("library:model-detail", kwargs={"pk": self.object.pk})


class VendorModelDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        device = get_object_or_404(VendorModel, pk=pk)
        name = f"{device.vendor.name} {device.model_number}"
        record_history(device, DeviceHistory.Action.DELETED, request.user)
        log_action(request, "deleted", device)
        device.delete()
        messages.success(request, f"Model \"{name}\" has been deleted.")
        return redirect("library:model-list")


# === Registers ===


class RegisterListView(LoginRequiredMixin, ListView):
    """Redirect to device detail (registers shown inline)."""

    def get(self, request, device_pk):
        return redirect("library:model-detail", pk=device_pk)


class RegisterCreateView(LoginRequiredMixin, CreateView):
    model = RegisterDefinition
    form_class = RegisterDefinitionForm
    template_name = "library/register_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
        return ctx

    def form_valid(self, form):
        device = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
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
        return reverse_lazy("library:model-detail", kwargs={"pk": self.kwargs["device_pk"]})


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
        return reverse_lazy("library:model-detail", kwargs={"pk": self.object.modbus_config.device_type.pk})


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
        return redirect("library:model-detail", pk=device.pk)


# === Device History ===


class DeviceHistoryDiffView(LoginRequiredMixin, TemplateView):
    template_name = "library/devicetype_history_diff.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        device = get_object_or_404(VendorModel, pk=self.kwargs["pk"])
        ctx["device"] = device

        from_version = int(self.request.GET.get("from", 0))
        to_version = int(self.request.GET.get("to", 0))

        from_entry = get_object_or_404(DeviceHistory, device=device, version=from_version)
        to_entry = get_object_or_404(DeviceHistory, device=device, version=to_version)

        ctx["from_entry"] = from_entry
        ctx["to_entry"] = to_entry
        ctx["diff"] = diff_snapshots(from_entry.snapshot, to_entry.snapshot)

        return ctx


class DeviceHistorySnapshotView(LoginRequiredMixin, TemplateView):
    """Read-only view of a device at a specific history version."""

    template_name = "library/devicetype_history_snapshot.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        device = get_object_or_404(VendorModel, pk=self.kwargs["pk"])
        version = self.kwargs["version"]
        entry = get_object_or_404(DeviceHistory, device=device, version=version)

        snapshot = entry.snapshot
        ctx["device"] = device
        ctx["entry"] = entry
        ctx["snapshot"] = snapshot
        ctx["technology"] = snapshot.get("technology", "")
        ctx["modbus_config"] = snapshot.get("modbus_config")
        ctx["registers"] = snapshot.get("registers", [])
        ctx["lorawan_config"] = snapshot.get("lorawan_config")
        ctx["wmbus_config"] = snapshot.get("wmbus_config")
        ctx["control_config"] = snapshot.get("control_config")
        ctx["processor_config"] = snapshot.get("processor_config")

        # Version navigation and history
        all_versions = list(
            DeviceHistory.objects.filter(device=device)
            .order_by("version")
            .values_list("version", flat=True)
        )
        ctx["all_versions"] = all_versions
        ctx["latest_version"] = all_versions[-1] if all_versions else version
        idx = all_versions.index(version) if version in all_versions else -1
        ctx["prev_version"] = all_versions[idx - 1] if idx > 0 else None
        ctx["next_version"] = all_versions[idx + 1] if 0 <= idx < len(all_versions) - 1 else None

        # Full history for the timeline
        ctx["history"] = (
            DeviceHistory.objects.filter(device=device)
            .select_related("user")
            .order_by("-version")
        )

        return ctx


# === Import / Export ===


class ImportView(SuperuserRequiredMixin, TemplateView):
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
                log_action(
                    request,
                    "imported",
                    Vendor(),  # no single target — use category override
                    category=AuditLog.Category.IMPORT,
                    details={
                        "vendors_created": stats["vendors_created"],
                        "vendors_updated": stats["vendors_updated"],
                        "devices_created": stats["devices_created"],
                        "devices_updated": stats["devices_updated"],
                        "errors": len(stats.get("errors", [])),
                    },
                )
                return self.render_to_response(self.get_context_data(form=form, stats=stats))
            except Exception as e:
                messages.error(request, f"Import failed: {e}")

        return self.render_to_response(self.get_context_data(form=form))


class ExportView(SuperuserRequiredMixin, TemplateView):
    template_name = "library/export.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["default_output_dir"] = "/app/export/devices/"
        return ctx

    def post(self, request):
        output_dir = request.POST.get("output_dir", "/app/export/devices/")
        try:
            stats = export_to_yaml(output_dir=output_dir)
            log_action(request, "exported", Vendor(), category=AuditLog.Category.EXPORT, details=stats)
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


class VersionCompareView(LoginRequiredMixin, TemplateView):
    """Compare two library versions by diffing all device snapshots."""

    template_name = "library/version_compare.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from_ver = int(self.request.GET.get("from", 0))
        to_ver = int(self.request.GET.get("to", 0))

        from_version = get_object_or_404(LibraryVersion, version=from_ver)
        to_version = get_object_or_404(LibraryVersion, version=to_ver)
        ctx["from_version"] = from_version
        ctx["to_version"] = to_version

        # Build snapshot lookups for each version: {device_type_id: (label, snapshot)}
        def _build_snapshot_map(lib_version):
            entries = lib_version.device_changes.exclude(
                change_type=LibraryVersionDevice.ChangeType.REMOVED,
            )
            result = {}
            for entry in entries:
                if not entry.device_type_id:
                    continue
                snapshot = (
                    DeviceHistory.objects.filter(
                        device_id=entry.device_type_id,
                        version=entry.device_version,
                    )
                    .values_list("snapshot", flat=True)
                    .first()
                )
                if snapshot:
                    result[entry.device_type_id] = {
                        "label": entry.device_label,
                        "version": entry.device_version,
                        "snapshot": snapshot,
                    }
            return result

        from_map = _build_snapshot_map(from_version)
        to_map = _build_snapshot_map(to_version)

        # Also collect removed entries (no device_type_id) by label
        from_removed = {
            e.device_label
            for e in from_version.device_changes.filter(
                change_type=LibraryVersionDevice.ChangeType.REMOVED,
            )
        }
        to_removed = {
            e.device_label
            for e in to_version.device_changes.filter(
                change_type=LibraryVersionDevice.ChangeType.REMOVED,
            )
        }

        from .history import diff_snapshots

        all_device_ids = set(from_map) | set(to_map)
        added = []
        removed = []
        modified = []
        unchanged = 0

        for device_id in sorted(all_device_ids, key=lambda d: (from_map.get(d) or to_map.get(d))["label"]):
            in_from = device_id in from_map
            in_to = device_id in to_map

            if in_to and not in_from:
                added.append(to_map[device_id])
            elif in_from and not in_to:
                removed.append(from_map[device_id])
            else:
                old_snap = from_map[device_id]["snapshot"]
                new_snap = to_map[device_id]["snapshot"]
                diff = diff_snapshots(old_snap, new_snap)
                if diff:
                    modified.append({
                        "label": to_map[device_id]["label"],
                        "from_version": from_map[device_id]["version"],
                        "to_version": to_map[device_id]["version"],
                        "diff": diff,
                    })
                else:
                    unchanged += 1

        ctx["added"] = added
        ctx["removed"] = removed
        ctx["modified"] = modified
        ctx["unchanged_count"] = unchanged
        ctx["versions"] = LibraryVersion.objects.values_list("version", flat=True).order_by("version")

        return ctx


class VersionCreateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request):
        # Auto-compute next version number
        max_version = LibraryVersion.objects.aggregate(v=Max("version"))["v"] or 0
        new_version = max_version + 1

        # Backfill: ensure every VendorModel has at least one DeviceHistory entry
        devices_without_history = VendorModel.objects.filter(history__isnull=True)
        for device in devices_without_history:
            record_history(device, DeviceHistory.Action.CREATED, user=None)

        # Mark previous current version as not current
        LibraryVersion.objects.filter(is_current=True).update(is_current=False)

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
        for device in VendorModel.objects.select_related("vendor"):
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

        log_action(request, "created", lib_version)
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
            vendors[vendor_name].append(snapshot_to_schema(snapshot))

        # Build final document
        vendor_list = []
        for vendor_name in sorted(vendors):
            vendor_list.append({
                "name": vendor_name,
                "models": vendors[vendor_name],
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
        log_action(self.request, "created", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:apikey-list")


class APIKeyDetailView(LoginRequiredMixin, DetailView):
    template_name = "library/apikey_detail.html"
    model = APIKey
    context_object_name = "apikey"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["new_key"] = self.request.session.pop("new_api_key", None)
        return ctx


class APIKeyRevokeView(LoginRequiredMixin, View):
    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        apikey.is_active = False
        apikey.save(update_fields=["is_active"])
        log_action(request, "revoked", apikey)
        messages.success(request, f"API key '{apikey.name}' has been revoked.")
        return redirect("library:apikey-detail", pk=apikey.pk)


class APIKeyEnableView(LoginRequiredMixin, View):
    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        apikey.is_active = True
        apikey.save(update_fields=["is_active"])
        log_action(request, "enabled", apikey)
        messages.success(request, f"API key '{apikey.name}' has been enabled.")
        return redirect("library:apikey-detail", pk=apikey.pk)


class APIKeyRegenerateView(LoginRequiredMixin, View):
    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        from .models import generate_api_key
        apikey.key = generate_api_key()
        apikey.save(update_fields=["key"])
        request.session["new_api_key"] = apikey.key
        log_action(request, "regenerated", apikey)
        messages.success(request, f"API key '{apikey.name}' has been regenerated. Copy the new key now.")
        return redirect("library:apikey-detail", pk=apikey.pk)


class APIKeyDeleteView(LoginRequiredMixin, View):
    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        name = apikey.name
        log_action(request, "deleted", apikey)
        apikey.delete()
        messages.success(request, f"API key '{name}' has been deleted.")
        return redirect("library:apikey-list")
