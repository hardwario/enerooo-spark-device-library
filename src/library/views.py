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
from core.permissions import RoleRequiredMixin

from .exporters import export_to_yaml, snapshot_to_schema
from .forms import (
    APIKeyForm,
    ControlConfigForm,
    DeviceTypeForm,
    LoRaWANConfigForm,
    MetricForm,
    ModbusConfigForm,
    ProcessorConfigForm,
    RegisterDefinitionForm,
    VendorForm,
    VendorModelForm,
    WMBusConfigForm,
    YAMLImportForm,
)
from .history import (
    diff_snapshots,
    record_device_type_history,
    record_history,
    record_metric_history,
    snapshot_device,
    snapshot_device_type,
    snapshot_metric,
)
from .importers import import_from_yaml
from .models import (
    APIKey,
    ControlConfig,
    DeviceHistory,
    DeviceType,
    DeviceTypeHistory,
    GatewayAssignment,
    LibraryVersion,
    LibraryVersionDevice,
    LibraryVersionDeviceType,
    LibraryVersionMetric,
    LoRaWANConfig,
    Metric,
    MetricHistory,
    ModbusConfig,
    ProcessorConfig,
    RegisterDefinition,
    Vendor,
    VendorModel,
    WMBusConfig,
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


class VendorCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.EDITOR
    model = Vendor
    form_class = VendorForm
    template_name = "library/vendor_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, "created", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:vendor-detail", kwargs={"slug": self.object.slug})


class VendorDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.EDITOR

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


# === Metrics ===


class MetricListView(LoginRequiredMixin, ListView):
    """L1 catalogue browser with usage stats (L2 type declarations, L4 model mappings)."""

    model = Metric
    template_name = "library/metric_list.html"
    context_object_name = "metrics"

    ALLOWED_SORT_FIELDS = {"key", "label", "unit", "data_type", "model_count", "type_count"}

    def get_queryset(self):
        qs = Metric.objects.all()
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(key__icontains=q) | Q(label__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")

        # Single-pass aggregation over JSON fields — no FK constraint on
        # metric keys, so we have to scan the rows. ~30 types × ~30 entries
        # and ~30 ProcessorConfigs × ~10 entries is trivial.
        type_counts: dict[str, int] = {}
        for dt in DeviceType.objects.all():
            for entry in (dt.metrics or []):
                key = entry.get("metric")
                if key:
                    type_counts[key] = type_counts.get(key, 0) + 1

        model_counts: dict[str, int] = {}
        for pc in ProcessorConfig.objects.exclude(field_mappings=[]):
            seen_in_this_model = set()
            for entry in (pc.field_mappings or []):
                key = entry.get("target")
                if key and key not in seen_in_this_model:
                    seen_in_this_model.add(key)
                    model_counts[key] = model_counts.get(key, 0) + 1

        # Attach counts onto each Metric instance so the template can render
        # them directly. Then apply sort + namespace facet here, after the
        # counts are known (allows sorting by usage).
        metrics = list(ctx["metrics"])
        for m in metrics:
            m.type_count = type_counts.get(m.key, 0)
            m.model_count = model_counts.get(m.key, 0)

        sort = self.request.GET.get("sort", "key")
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        if field not in self.ALLOWED_SORT_FIELDS:
            field, descending = "key", False
        metrics.sort(key=lambda m: getattr(m, field) or "", reverse=descending)

        ctx["metrics"] = metrics
        ctx["namespaces"] = sorted({m.namespace for m in metrics if m.namespace})
        ctx["unused_count"] = sum(1 for m in metrics if not m.type_count and not m.model_count)
        return ctx


class MetricDetailView(LoginRequiredMixin, DetailView):
    """L1 metric detail with L2 (DeviceTypes declaring it) and L4 (VendorModels
    mapping a decoded field to it) usage breakdown."""

    model = Metric
    template_name = "library/metric_detail.html"
    context_object_name = "metric"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        key = self.object.key

        # L2 — DeviceTypes that declare this metric in their profile
        declared_in = []
        for dt in DeviceType.objects.all():
            for entry in (dt.metrics or []):
                if entry.get("metric") == key:
                    declared_in.append({
                        "device_type": dt,
                        "tier": entry.get("tier") or "secondary",
                    })
                    break
        ctx["declared_in"] = declared_in

        # L4 — VendorModels whose ProcessorConfig.field_mappings target this metric
        mapped_by = []
        for pc in ProcessorConfig.objects.exclude(field_mappings=[]).select_related("device_type__vendor", "device_type__device_type_fk"):
            matches = [e for e in (pc.field_mappings or []) if e.get("target") == key]
            if matches:
                mapped_by.append({
                    "vendor_model": pc.device_type,
                    "entries": matches,
                })
        mapped_by.sort(key=lambda m: (m["vendor_model"].vendor.name, m["vendor_model"].model_number))
        ctx["mapped_by"] = mapped_by

        # Change history — same shape/cap as VendorModelDetailView for
        # consistency across the three versioned entity types.
        ctx["history"] = self.object.history.select_related("user").all()[:20]

        return ctx


def _count_metric_references(metric_key: str) -> int:
    """Return the number of ProcessorConfig.field_mappings entries whose
    ``target`` points at this metric. Used to warn the operator before delete."""
    count = 0
    for pc in ProcessorConfig.objects.exclude(field_mappings=[]):
        for entry in pc.field_mappings or []:
            if entry.get("target") == metric_key:
                count += 1
    return count


class MetricCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.ADMIN
    model = Metric
    form_class = MetricForm
    template_name = "library/metric_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        record_metric_history(self.object, MetricHistory.Action.CREATED, self.request.user)
        log_action(self.request, "created", self.object)
        messages.success(self.request, f"Metric '{self.object.key}' created.")
        return response

    def get_success_url(self):
        return reverse_lazy("library:metric-list")


class MetricUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.ADMIN
    model = Metric
    form_class = MetricForm
    template_name = "library/metric_form.html"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        # Capture pre-edit snapshot so the diff in record_metric_history
        # has something to compare against.
        self._old_snapshot = snapshot_metric(obj)
        return obj

    def form_valid(self, form):
        response = super().form_valid(form)
        record_metric_history(
            self.object,
            MetricHistory.Action.UPDATED,
            self.request.user,
            previous_snapshot=self._old_snapshot,
        )
        log_action(self.request, "updated", self.object)
        messages.success(self.request, f"Metric '{self.object.key}' updated.")
        return response

    def get_success_url(self):
        return reverse_lazy("library:metric-list")


class MetricDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def get(self, request, pk):
        metric = get_object_or_404(Metric, pk=pk)
        return self._render_confirm(request, metric)

    def post(self, request, pk):
        metric = get_object_or_404(Metric, pk=pk)
        references = _count_metric_references(metric.key)
        if references and not request.POST.get("confirm_force"):
            messages.error(
                request,
                f"Cannot delete '{metric.key}' — {references} VendorModel field mapping(s) reference it. "
                "Remove those references first, or tick 'Force delete' on the confirmation form.",
            )
            return redirect("library:metric-delete", pk=metric.pk)
        key = metric.key
        # Capture pre-delete snapshot for the audit trail before the row
        # vanishes. ``record_metric_history`` writes the entry with FK
        # ``metric`` populated; the post-delete SET_NULL kicks in after
        # the row is gone, leaving the history row with a NULL FK but
        # the ``metric_key`` column preserved for grep-ability.
        old_snapshot = snapshot_metric(metric)
        record_metric_history(
            metric,
            MetricHistory.Action.DELETED,
            request.user,
            previous_snapshot=old_snapshot,
        )
        log_action(request, "deleted", metric)
        metric.delete()
        messages.success(request, f"Metric '{key}' deleted.")
        return redirect("library:metric-list")

    def _render_confirm(self, request, metric):
        from django.shortcuts import render
        return render(
            request,
            "library/metric_confirm_delete.html",
            {
                "metric": metric,
                "reference_count": _count_metric_references(metric.key),
            },
        )


# === Device Types ===


class DeviceTypeListView(LoginRequiredMixin, ListView):
    model = DeviceType
    template_name = "library/device_type/list.html"
    context_object_name = "device_types"

    def get_queryset(self):
        return DeviceType.objects.annotate(
            vendor_model_count=Count("vendor_models"),
        ).order_by("label")


class DeviceTypeDetailView(LoginRequiredMixin, DetailView):
    model = DeviceType
    template_name = "library/device_type/detail.html"
    context_object_name = "device_type"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["vendor_models"] = self.object.vendor_models.select_related("vendor").order_by(
            "vendor__name", "model_number",
        )
        ctx["history"] = self.object.history.select_related("user").all()[:20]
        return ctx


class DeviceTypeCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.ADMIN
    model = DeviceType
    form_class = DeviceTypeForm
    template_name = "library/device_type/form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        record_device_type_history(self.object, DeviceTypeHistory.Action.CREATED, self.request.user)
        log_action(self.request, "created", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:devicetype-detail", kwargs={"pk": self.object.pk})


class DeviceTypeUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.ADMIN
    model = DeviceType
    form_class = DeviceTypeForm
    template_name = "library/device_type/form.html"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        self._old_snapshot = snapshot_device_type(obj)
        return obj

    def form_valid(self, form):
        response = super().form_valid(form)
        record_device_type_history(
            self.object,
            DeviceTypeHistory.Action.UPDATED,
            self.request.user,
            previous_snapshot=self._old_snapshot,
        )
        log_action(self.request, "updated", self.object)
        return response

    def get_success_url(self):
        return reverse_lazy("library:devicetype-detail", kwargs={"pk": self.object.pk})


class DeviceTypeDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, pk):
        dt = get_object_or_404(DeviceType, pk=pk)
        if dt.vendor_models.exists():
            messages.error(
                request,
                f"Cannot delete {dt.label} — {dt.vendor_models.count()} VendorModel(s) "
                "still point at it. Re-assign them first.",
            )
            return redirect("library:devicetype-detail", pk=dt.pk)
        label = dt.label
        # Snapshot for audit trail before the row is gone (see MetricDeleteView).
        old_snapshot = snapshot_device_type(dt)
        record_device_type_history(
            dt,
            DeviceTypeHistory.Action.DELETED,
            request.user,
            previous_snapshot=old_snapshot,
        )
        log_action(request, "deleted", dt)
        dt.delete()
        messages.success(request, f"Device type \"{label}\" deleted.")
        return redirect("library:devicetype-list")


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


class VendorModelCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.EDITOR
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


class VendorModelUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
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


class VendorModelDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.EDITOR

    def post(self, request, pk):
        device = get_object_or_404(VendorModel, pk=pk)
        name = f"{device.vendor.name} {device.model_number}"
        record_history(device, DeviceHistory.Action.DELETED, request.user)
        log_action(request, "deleted", device)
        device.delete()
        messages.success(request, f"Model \"{name}\" has been deleted.")
        return redirect("library:model-list")


# === Modbus Config ===


class ModbusConfigUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
    model = ModbusConfig
    form_class = ModbusConfigForm
    template_name = "library/modbus_config_form.html"

    def get_object(self, queryset=None):
        device = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
        self._device = device
        self._old_snapshot = snapshot_device(device)
        obj, _ = ModbusConfig.objects.get_or_create(device_type=device)
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self._device
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        # Re-fetch device so snapshot picks up saved config (cached reverse relation is stale)
        device = VendorModel.objects.get(pk=self._device.pk)
        record_history(device, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", form.instance, details=f"Modbus config updated on {self._device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:model-detail", kwargs={"pk": self._device.pk})


# === Control Config ===


class ControlConfigUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
    model = ControlConfig
    form_class = ControlConfigForm
    template_name = "library/control_config_form.html"

    def get_object(self, queryset=None):
        device = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
        self._device = device
        self._old_snapshot = snapshot_device(device)
        obj, _ = ControlConfig.objects.get_or_create(device_type=device)
        return obj

    def get_context_data(self, **kwargs):
        from .control_examples import archetypes_for_template

        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self._device
        ctx["control_archetypes"] = archetypes_for_template()
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        device = VendorModel.objects.get(pk=self._device.pk)
        record_history(device, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", form.instance, details=f"Control config updated on {self._device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:model-detail", kwargs={"pk": self._device.pk})


# === wM-Bus Config ===


class WMBusConfigUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
    model = WMBusConfig
    form_class = WMBusConfigForm
    template_name = "library/wmbus_config_form.html"

    def get_object(self, queryset=None):
        device = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
        self._device = device
        self._old_snapshot = snapshot_device(device)
        obj, _ = WMBusConfig.objects.get_or_create(device_type=device)
        return obj

    def get_initial(self):
        initial = super().get_initial()
        if not self.object.wmbusmeters_driver:
            initial["wmbusmeters_driver"] = "auto"
        return initial

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self._device
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        device = VendorModel.objects.get(pk=self._device.pk)
        record_history(device, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", form.instance, details=f"wM-Bus config updated on {self._device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:model-detail", kwargs={"pk": self._device.pk})


# === LoRaWAN Config ===


class LoRaWANConfigUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
    model = LoRaWANConfig
    form_class = LoRaWANConfigForm
    template_name = "library/lorawan_config_form.html"

    def get_object(self, queryset=None):
        device = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
        self._device = device
        self._old_snapshot = snapshot_device(device)
        obj, _ = LoRaWANConfig.objects.get_or_create(device_type=device)
        return obj

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self._device
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        device = VendorModel.objects.get(pk=self._device.pk)
        record_history(device, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", form.instance, details=f"LoRaWAN config updated on {self._device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:model-detail", kwargs={"pk": self._device.pk})


# === Processor Config ===


class ProcessorConfigUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
    model = ProcessorConfig
    form_class = ProcessorConfigForm
    template_name = "library/processor_config_form.html"

    def get_object(self, queryset=None):
        device = get_object_or_404(VendorModel, pk=self.kwargs["device_pk"])
        self._device = device
        self._old_snapshot = snapshot_device(device)
        obj, _ = ProcessorConfig.objects.get_or_create(device_type=device)
        return obj

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["vendor_model"] = self._device
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self._device
        return ctx

    def form_valid(self, form):
        response = super().form_valid(form)
        device = VendorModel.objects.get(pk=self._device.pk)
        record_history(device, DeviceHistory.Action.UPDATED, self.request.user, self._old_snapshot)
        log_action(self.request, "updated", form.instance, details=f"Processor config updated on {self._device}")
        return response

    def get_success_url(self):
        return reverse_lazy("library:model-detail", kwargs={"pk": self._device.pk})


# === Registers ===


class RegisterListView(LoginRequiredMixin, ListView):
    """Redirect to device detail (registers shown inline)."""

    def get(self, request, device_pk):
        return redirect("library:model-detail", pk=device_pk)


class RegisterCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.EDITOR
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


class RegisterUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
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


class RegisterDeleteView(RoleRequiredMixin, DeleteView):
    required_role = User.Role.EDITOR
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


class MetricHistoryDiffView(LoginRequiredMixin, TemplateView):
    """Side-by-side diff between two ``MetricHistory`` versions of the
    same Metric row. Mirrors ``DeviceHistoryDiffView`` for parity."""

    template_name = "library/metric_history_diff.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        metric = get_object_or_404(Metric, pk=self.kwargs["pk"])
        from_version = int(self.request.GET.get("from", 0))
        to_version = int(self.request.GET.get("to", 0))

        from_entry = get_object_or_404(MetricHistory, metric=metric, version=from_version)
        to_entry = get_object_or_404(MetricHistory, metric=metric, version=to_version)

        ctx["metric"] = metric
        ctx["from_entry"] = from_entry
        ctx["to_entry"] = to_entry
        ctx["diff"] = diff_snapshots(from_entry.snapshot, to_entry.snapshot)
        return ctx


class MetricHistorySnapshotView(LoginRequiredMixin, TemplateView):
    """Read-only view of a Metric at a specific history version."""

    template_name = "library/metric_history_snapshot.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        metric = get_object_or_404(Metric, pk=self.kwargs["pk"])
        version = self.kwargs["version"]
        entry = get_object_or_404(MetricHistory, metric=metric, version=version)

        ctx["metric"] = metric
        ctx["entry"] = entry
        ctx["snapshot"] = entry.snapshot

        all_versions = list(
            MetricHistory.objects.filter(metric=metric)
            .order_by("version")
            .values_list("version", flat=True)
        )
        ctx["all_versions"] = all_versions
        ctx["latest_version"] = all_versions[-1] if all_versions else version
        idx = all_versions.index(version) if version in all_versions else -1
        ctx["prev_version"] = all_versions[idx - 1] if idx > 0 else None
        ctx["next_version"] = all_versions[idx + 1] if 0 <= idx < len(all_versions) - 1 else None

        ctx["history"] = (
            MetricHistory.objects.filter(metric=metric)
            .select_related("user")
            .order_by("-version")
        )
        return ctx


class DeviceTypeHistoryDiffView(LoginRequiredMixin, TemplateView):
    """Side-by-side diff between two ``DeviceTypeHistory`` versions."""

    template_name = "library/devicetype_kind_history_diff.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dt = get_object_or_404(DeviceType, pk=self.kwargs["pk"])
        from_version = int(self.request.GET.get("from", 0))
        to_version = int(self.request.GET.get("to", 0))

        from_entry = get_object_or_404(DeviceTypeHistory, device_type=dt, version=from_version)
        to_entry = get_object_or_404(DeviceTypeHistory, device_type=dt, version=to_version)

        ctx["device_type"] = dt
        ctx["from_entry"] = from_entry
        ctx["to_entry"] = to_entry
        ctx["diff"] = diff_snapshots(from_entry.snapshot, to_entry.snapshot)
        return ctx


class DeviceTypeHistorySnapshotView(LoginRequiredMixin, TemplateView):
    """Read-only view of a DeviceType at a specific history version."""

    template_name = "library/devicetype_kind_history_snapshot.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        dt = get_object_or_404(DeviceType, pk=self.kwargs["pk"])
        version = self.kwargs["version"]
        entry = get_object_or_404(DeviceTypeHistory, device_type=dt, version=version)

        ctx["device_type"] = dt
        ctx["entry"] = entry
        ctx["snapshot"] = entry.snapshot

        all_versions = list(
            DeviceTypeHistory.objects.filter(device_type=dt)
            .order_by("version")
            .values_list("version", flat=True)
        )
        ctx["all_versions"] = all_versions
        ctx["latest_version"] = all_versions[-1] if all_versions else version
        idx = all_versions.index(version) if version in all_versions else -1
        ctx["prev_version"] = all_versions[idx - 1] if idx > 0 else None
        ctx["next_version"] = all_versions[idx + 1] if 0 <= idx < len(all_versions) - 1 else None

        ctx["history"] = (
            DeviceTypeHistory.objects.filter(device_type=dt)
            .select_related("user")
            .order_by("-version")
        )
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


class ImportView(RoleRequiredMixin, TemplateView):
    required_role = User.Role.ADMIN
    template_name = "library/import.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if "form" not in ctx:
            ctx["form"] = YAMLImportForm(initial={
                "devices_path": "",
                "manifest_path": "",
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


class ExportView(RoleRequiredMixin, TemplateView):
    required_role = User.Role.ADMIN
    template_name = "library/export.html"


class ExportDownloadView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN
    """Export all device definitions as a downloadable ZIP archive."""

    def post(self, request):
        import tempfile
        import zipfile
        from io import BytesIO

        with tempfile.TemporaryDirectory() as tmpdir:
            stats = export_to_yaml(output_dir=f"{tmpdir}/devices/")
            log_action(request, "exported", Vendor(), category=AuditLog.Category.EXPORT, details=stats)

            buf = BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                from pathlib import Path
                base = Path(tmpdir)
                for f in sorted(base.rglob("*")):
                    if f.is_file():
                        zf.write(f, f.relative_to(base))

            buf.seek(0)
            response = HttpResponse(buf.read(), content_type="application/zip")
            response["Content-Disposition"] = 'attachment; filename="device-library-export.zip"'
            return response


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

        # ``?show_unchanged=1`` switches the page from "diff view" (only
        # added/modified/removed — the story of this version) to "full
        # inventory" mode. Default is diff view because that's almost
        # always what brings an operator to a version detail page.
        show_unchanged = self.request.GET.get("show_unchanged") in {"1", "true", "yes"}
        ctx["show_unchanged"] = show_unchanged

        def _filter(qs, change_type_enum):
            """Total / changed counts come from the unfiltered queryset
            so the section headers are accurate regardless of view mode."""
            total = qs.exclude(change_type=change_type_enum.REMOVED).count()
            changed = qs.exclude(change_type=change_type_enum.UNCHANGED).count()
            unchanged = total - (changed - qs.filter(change_type=change_type_enum.REMOVED).count())
            visible = qs if show_unchanged else qs.exclude(change_type=change_type_enum.UNCHANGED)
            return visible, total, changed, unchanged

        # Model manifest (VendorModel).
        device_qs = self.object.device_changes.select_related("device_type", "device_type__vendor").all()
        visible, total, changed, unchanged = _filter(device_qs, LibraryVersionDevice.ChangeType)
        ctx["manifest"] = visible
        ctx["device_count"] = total
        ctx["changed_count"] = changed
        ctx["unchanged_count"] = unchanged

        # Metric manifest (L1).
        metric_qs = self.object.metric_changes.select_related("metric").all()
        visible, total, changed, unchanged = _filter(metric_qs, LibraryVersionMetric.ChangeType)
        ctx["metric_manifest"] = visible
        ctx["metric_count"] = total
        ctx["metric_changed_count"] = changed
        ctx["metric_unchanged_count"] = unchanged

        # DeviceType manifest (L2).
        device_type_qs = self.object.device_type_changes.select_related("device_type").all()
        visible, total, changed, unchanged = _filter(device_type_qs, LibraryVersionDeviceType.ChangeType)
        ctx["device_type_manifest"] = visible
        ctx["device_type_count"] = total
        ctx["device_type_changed_count"] = changed
        ctx["device_type_unchanged_count"] = unchanged

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

        # -----------------------------------------------------------------
        # L1 Metric + L2 DeviceType manifest entries — same publish flow
        # as VendorModel above, applied to the two other versioned entity
        # types. Without these, retrieve(version=N) would have to fall
        # back to ``Metric.objects.all()`` and serve the *current* state
        # rather than the v=N snapshot — see ``LibraryContentViewSet``.
        # -----------------------------------------------------------------
        self._publish_entities(
            lib_version,
            prev_version,
            Metric, MetricHistory,
            LibraryVersionMetric,
            link_attr="metric",
            label_attr="key",
            version_attr="metric_version",
            label_field="metric_key",
            prev_relation="metric_changes",
        )
        self._publish_entities(
            lib_version,
            prev_version,
            DeviceType, DeviceTypeHistory,
            LibraryVersionDeviceType,
            link_attr="device_type",
            label_attr="code",
            version_attr="device_type_version",
            label_field="device_type_code",
            prev_relation="device_type_changes",
        )

        log_action(request, "created", lib_version)
        messages.success(request, f"Library version v{new_version} created.")
        return redirect("library:version-detail", pk=lib_version.pk)

    def _publish_entities(
        self,
        lib_version,
        prev_version,
        entity_model,
        history_model,
        link_model,
        *,
        link_attr,         # FK name on link_model ("metric" / "device_type")
        label_attr,        # field on entity_model used as label ("key" / "code")
        version_attr,      # version field on link_model ("metric_version" / …)
        label_field,       # label field on link_model ("metric_key" / "device_type_code")
        prev_relation,     # reverse FK on LibraryVersion ("metric_changes" / …)
    ):
        """Generic publish step for an L1/L2 entity that mirrors the
        VendorModel block above. Factored out to keep the two new
        entity types from duplicating ~30 lines each."""
        # Backfill: any entity row without a history entry gets a v1
        # CREATED snapshot so the publish flow can reference it.
        record_fn = (
            record_metric_history if entity_model is Metric else record_device_type_history
        )
        action_created = (
            MetricHistory.Action.CREATED
            if entity_model is Metric
            else DeviceTypeHistory.Action.CREATED
        )
        for ent in entity_model.objects.filter(history__isnull=True):
            record_fn(ent, action_created, user=None)

        # Previous manifest: which entity → which history version was pinned
        prev_manifest: dict = {}
        if prev_version:
            for entry in getattr(prev_version, prev_relation).all():
                fk_id = getattr(entry, f"{link_attr}_id")
                if fk_id and entry.change_type != link_model.ChangeType.REMOVED:
                    prev_manifest[fk_id] = getattr(entry, version_attr)

        current_ids: set = set()
        for ent in entity_model.objects.all():
            current_ids.add(ent.pk)
            latest_version = (
                history_model.objects.filter(**{link_attr: ent})
                .order_by("-version")
                .values_list("version", flat=True)
                .first()
            ) or 1

            if ent.pk in prev_manifest:
                change_type = (
                    link_model.ChangeType.UNCHANGED
                    if prev_manifest[ent.pk] == latest_version
                    else link_model.ChangeType.MODIFIED
                )
            else:
                change_type = link_model.ChangeType.ADDED

            link_model.objects.create(
                library_version=lib_version,
                **{link_attr: ent},
                **{version_attr: latest_version},
                **{label_field: getattr(ent, label_attr)},
                change_type=change_type,
            )

        if prev_version:
            for prev_id, prev_ver in prev_manifest.items():
                if prev_id in current_ids:
                    continue
                prev_entry = (
                    getattr(prev_version, prev_relation)
                    .filter(**{f"{link_attr}_id": prev_id})
                    .first()
                )
                label = getattr(prev_entry, label_field) if prev_entry else f"Deleted {label_attr}"
                link_model.objects.create(
                    library_version=lib_version,
                    **{link_attr: None},
                    **{version_attr: prev_ver},
                    **{label_field: label},
                    change_type=link_model.ChangeType.REMOVED,
                )


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


class APIKeyCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.ADMIN
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


class APIKeyRevokeView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        apikey.is_active = False
        apikey.save(update_fields=["is_active"])
        log_action(request, "revoked", apikey)
        messages.success(request, f"API key '{apikey.name}' has been revoked.")
        return redirect("library:apikey-detail", pk=apikey.pk)


class APIKeyEnableView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        apikey.is_active = True
        apikey.save(update_fields=["is_active"])
        log_action(request, "enabled", apikey)
        messages.success(request, f"API key '{apikey.name}' has been enabled.")
        return redirect("library:apikey-detail", pk=apikey.pk)


class APIKeyRegenerateView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        from .models import generate_api_key
        apikey.key = generate_api_key()
        apikey.save(update_fields=["key"])
        request.session["new_api_key"] = apikey.key
        log_action(request, "regenerated", apikey)
        messages.success(request, f"API key '{apikey.name}' has been regenerated. Copy the new key now.")
        return redirect("library:apikey-detail", pk=apikey.pk)


class APIKeyDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.ADMIN

    def post(self, request, pk):
        apikey = get_object_or_404(APIKey, pk=pk)
        name = apikey.name
        log_action(request, "deleted", apikey)
        apikey.delete()
        messages.success(request, f"API key '{name}' has been deleted.")
        return redirect("library:apikey-list")


# === wM-Bus Mapping Table ===


class WMBusMappingView(LoginRequiredMixin, ListView):
    template_name = "library/wmbus_mapping.html"
    context_object_name = "mappings"
    ALLOWED_SORT_FIELDS = {
        "manufacturer_code": "manufacturer_code",
        "wmbus_version": "wmbus_version",
        "wmbus_device_type": "wmbus_device_type",
        "vendor": "device_type__vendor__name",
        "model": "device_type__name",
        "driver": "wmbusmeters_driver",
        "encryption": "encryption_required",
        "mvt_default": "is_mvt_default",
    }

    def get_queryset(self):
        qs = WMBusConfig.objects.select_related("device_type__vendor")

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(manufacturer_code__icontains=q)
                | Q(wmbusmeters_driver__icontains=q)
                | Q(device_type__name__icontains=q)
                | Q(device_type__vendor__name__icontains=q)
                | Q(device_type__model_number__icontains=q)
            )

        sort = self.request.GET.get("sort", "manufacturer_code")
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        db_field = self.ALLOWED_SORT_FIELDS.get(field, "manufacturer_code")
        order = f"-{db_field}" if descending else db_field
        return qs.order_by(order, "wmbus_device_type")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["current_sort"] = self.request.GET.get("sort", "manufacturer_code")
        return ctx


# === Gateway Assignments ===


class GatewayAssignmentListView(LoginRequiredMixin, ListView):
    template_name = "library/gateway_list.html"
    context_object_name = "assignments"
    ALLOWED_SORT_FIELDS = {
        "serial_number": "serial_number",
        "is_registered": "is_registered",
        "is_assigned": "is_assigned",
        "spark_url": "spark_url",
        "assigned_by": "assigned_by",
        "last_seen": "last_seen",
    }

    def get_queryset(self):
        qs = GatewayAssignment.objects.all()

        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(serial_number__icontains=q)
                | Q(spark_url__icontains=q)
                | Q(assigned_by__icontains=q)
            )

        sort = self.request.GET.get("sort", "serial_number")
        descending = sort.startswith("-")
        field = sort.lstrip("-")
        db_field = self.ALLOWED_SORT_FIELDS.get(field, "serial_number")
        order = f"-{db_field}" if descending else db_field
        return qs.order_by(order)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["search_query"] = self.request.GET.get("q", "")
        ctx["current_sort"] = self.request.GET.get("sort", "serial_number")
        return ctx


class GatewayAssignmentCreateView(RoleRequiredMixin, CreateView):
    required_role = User.Role.EDITOR
    model = GatewayAssignment
    fields = ["serial_number", "spark_url"]
    template_name = "library/gateway_form.html"

    def form_valid(self, form):
        form.instance.assigned_by = self.request.user.get_full_name() or self.request.user.username
        response = super().form_valid(form)
        log_action(self.request, "created", self.object)
        messages.success(self.request, f"Gateway assignment '{self.object.serial_number}' created.")
        return response

    def get_success_url(self):
        return reverse_lazy("library:gateway-list")


class GatewayAssignmentUpdateView(RoleRequiredMixin, UpdateView):
    required_role = User.Role.EDITOR
    model = GatewayAssignment
    fields = ["serial_number", "spark_url", "is_registered", "is_assigned"]
    template_name = "library/gateway_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        log_action(self.request, "updated", self.object)
        messages.success(self.request, f"Gateway assignment '{self.object.serial_number}' updated.")
        return response

    def get_success_url(self):
        return reverse_lazy("library:gateway-list")


class GatewayAssignmentDeleteView(RoleRequiredMixin, View):
    required_role = User.Role.EDITOR

    def post(self, request, pk):
        assignment = get_object_or_404(GatewayAssignment, pk=pk)
        serial = assignment.serial_number
        log_action(request, "deleted", assignment)
        assignment.delete()
        messages.success(request, f"Gateway assignment '{serial}' has been deleted.")
        return redirect("library:gateway-list")
