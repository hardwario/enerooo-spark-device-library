"""Library views for the web UI."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from .exporters import export_to_yaml
from .forms import APIKeyForm, DeviceTypeForm, LibraryVersionForm, RegisterDefinitionForm, YAMLImportForm
from .importers import import_from_yaml
from .models import (
    APIKey,
    DeviceType,
    LibraryVersion,
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
        ctx["current_version"] = current.version if current else None
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

    def get_queryset(self):
        return Vendor.objects.annotate(device_count=Count("device_types"))


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

    def get_queryset(self):
        qs = DeviceType.objects.select_related("vendor")
        vendor = self.request.GET.get("vendor")
        technology = self.request.GET.get("technology")
        device_type = self.request.GET.get("device_type")

        if vendor:
            qs = qs.filter(vendor__slug=vendor)
        if technology:
            qs = qs.filter(technology=technology)
        if device_type:
            qs = qs.filter(device_type=device_type)

        return qs

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

        return ctx


class DeviceTypeCreateView(LoginRequiredMixin, CreateView):
    model = DeviceType
    form_class = DeviceTypeForm
    template_name = "library/devicetype_form.html"

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.pk})


class DeviceTypeUpdateView(LoginRequiredMixin, UpdateView):
    model = DeviceType
    form_class = DeviceTypeForm
    template_name = "library/devicetype_form.html"

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.pk})


class DeviceTypeDeleteView(LoginRequiredMixin, DeleteView):
    model = DeviceType
    template_name = "library/devicetype_confirm_delete.html"
    success_url = reverse_lazy("library:device-list")


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
        # Ensure modbus config exists
        from .models import ModbusConfig

        modbus_config, _ = ModbusConfig.objects.get_or_create(device_type=device)
        form.instance.modbus_config = modbus_config
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.kwargs["device_pk"]})


class RegisterUpdateView(LoginRequiredMixin, UpdateView):
    model = RegisterDefinition
    form_class = RegisterDefinitionForm
    template_name = "library/register_form.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["device"] = self.object.modbus_config.device_type
        return ctx

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.modbus_config.device_type.pk})


class RegisterDeleteView(LoginRequiredMixin, DeleteView):
    model = RegisterDefinition
    template_name = "library/register_confirm_delete.html"

    def get_success_url(self):
        return reverse_lazy("library:device-detail", kwargs={"pk": self.object.modbus_config.device_type.pk})


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
        ctx["changes"] = self.object.device_changes.select_related("device_type").all()
        return ctx


class VersionCreateView(LoginRequiredMixin, CreateView):
    model = LibraryVersion
    form_class = LibraryVersionForm
    template_name = "library/version_form.html"

    def form_valid(self, form):
        form.instance.published_by = self.request.user
        form.instance.is_current = True
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy("library:version-detail", kwargs={"pk": self.object.pk})


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
