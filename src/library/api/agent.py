"""Agent API — the surface the library MCP server talks to.

Read endpoints answer "what does the library know about this model" with the
same full snapshot the history/versioning layer stores, so an AI agent sees
exactly what a publish would ship. Write endpoints cover what the UI can edit
— vendor models and their per-technology configs, plus the L1/L2 catalogues
(vendors, metrics, device types, alarms) and Modbus registers — and every one
of them is backed by the *same Django form the UI uses*, so validation and
history behaviour cannot drift from the human path. Writes use merge
semantics: omitted fields keep their current value.

Deliberately NOT exposed: publishing a LibraryVersion (the human review
gate), API key management, YAML import/export, user administration.

Safety model:
- Auth: X-API-Key (``HasAPIKey``), same keys the sync API uses.
- Writes are additionally gated by the ``AGENT_API_ALLOW_WRITES`` setting
  (env, default off) — a read-only deployment stays read-only even if a key
  leaks.
- Attribution: agent writes record history under a dedicated ``mcp-agent``
  service user, so they are distinguishable from human edits in the history
  UI and trivially revertable.
- Every edit is a draft: Spark instances receive only what a human reviews
  and publishes.
"""

from __future__ import annotations

from dataclasses import asdict

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.forms.models import model_to_dict
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from library.forms import (
    AlarmConfigForm,
    AlarmForm,
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
)
from library.history import (
    record_device_type_history,
    record_history,
    record_metric_history,
    snapshot_device,
    snapshot_device_type,
    snapshot_metric,
)
from library.models import (
    Alarm,
    DeviceHistory,
    DeviceType,
    DeviceTypeHistory,
    LibraryVersion,
    Metric,
    MetricHistory,
    RegisterDefinition,
    Vendor,
    VendorModel,
)
from library.unpublished import unpublished_changes_summary

from .permissions import HasAPIKey

AGENT_USERNAME = "mcp-agent"

# Per-model config sections: section slug → (form, one-to-one accessor).
CONFIG_SECTIONS = {
    "processor": (ProcessorConfigForm, "processor_config"),
    "alarm": (AlarmConfigForm, "alarm_config"),
    "modbus": (ModbusConfigForm, "modbus_config"),
    "wmbus": (WMBusConfigForm, "wmbus_config"),
    "lorawan": (LoRaWANConfigForm, "lorawan_config"),
    "control": (ControlConfigForm, "control_config"),
}

# Catalogue entities: kind slug → (model, form). Metric and DeviceType carry
# their own history tables; Vendor and Alarm do not (mirrors the UI).
CATALOG = {
    "vendors": (Vendor, VendorForm),
    "metrics": (Metric, MetricForm),
    "device_types": (DeviceType, DeviceTypeForm),
    "alarms": (Alarm, AlarmForm),
}


def _agent_user():
    """The service user agent writes are attributed to (created on first use)."""
    user_model = get_user_model()
    user, _ = user_model.objects.get_or_create(
        username=AGENT_USERNAME,
        defaults={"is_active": False, "first_name": "MCP", "last_name": "Agent"},
    )
    return user


def _writes_disabled() -> Response | None:
    if not settings.AGENT_API_ALLOW_WRITES:
        return Response(
            {"error": "Agent writes are disabled (AGENT_API_ALLOW_WRITES)."},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _merged_form(form_class, instance, data: dict, **form_kwargs):
    """Instantiate a UI form with merge semantics: current values overlaid
    with the fields the request provides, so a partial write never clobbers
    the rest through the form's full-replacement contract."""
    base = model_to_dict(instance) if instance is not None else {}
    base.update(data or {})
    return form_class(data=base, instance=instance, **form_kwargs)


def _model_brief(model: VendorModel) -> dict:
    return {
        "key": str(model.key),
        "vendor": model.vendor.name if model.vendor else None,
        "name": model.name,
        "model_number": model.model_number,
        "technology": model.technology,
        "device_type": model.device_type,
        "has_alarm_config": hasattr(model, "alarm_config"),
    }


DRAFT_NOTE = (
    "Saved as a draft. A human must publish a library version "
    "for Spark instances to receive it."
)


class AgentModelViewSet(viewsets.ViewSet):
    """VendorModel reads and form-backed writes for the MCP agent."""

    permission_classes = [HasAPIKey]
    lookup_field = "key"

    def list(self, request):
        qs = VendorModel.objects.select_related("vendor").order_by("vendor__name", "name")
        technology = request.query_params.get("technology")
        if technology:
            qs = qs.filter(technology=technology)
        device_type = request.query_params.get("device_type")
        if device_type:
            qs = qs.filter(device_type=device_type)
        q = request.query_params.get("q")
        if q:
            qs = qs.filter(
                Q(name__icontains=q)
                | Q(model_number__icontains=q)
                | Q(vendor__name__icontains=q)
                | Q(wmbus_config__wmbusmeters_driver__icontains=q)
            ).distinct()
        if request.query_params.get("missing_alarm_config") in ("1", "true"):
            qs = qs.filter(alarm_config__isnull=True)
        return Response({
            "count": qs.count(),
            "models": [_model_brief(m) for m in qs[:200]],
            "truncated": qs.count() > 200,
        })

    def retrieve(self, request, key=None):
        model = get_object_or_404(VendorModel.objects.select_related("vendor"), key=key)
        registers = []
        modbus = getattr(model, "modbus_config", None)
        if modbus:
            registers = [
                {"id": str(r.id), **model_to_dict(r, exclude=["id", "modbus_config"])}
                for r in modbus.register_definitions.all()
            ]
        return Response({
            "key": str(model.key),
            "id": str(model.pk),
            "vendor_id": str(model.vendor_id) if model.vendor_id else None,
            "device_type_fk_id": str(model.device_type_fk_id) if model.device_type_fk_id else None,
            "snapshot": snapshot_device(model),
            "registers": registers,
        })

    def create(self, request):
        if resp := _writes_disabled():
            return resp
        form = VendorModelForm(data=request.data)
        if not form.is_valid():
            return Response({"error": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        model = form.save()
        record_history(model, DeviceHistory.Action.CREATED, _agent_user())
        return Response({"key": str(model.key), "note": DRAFT_NOTE},
                        status=status.HTTP_201_CREATED)

    def update(self, request, key=None):
        """Edit the model's own fields (name, model_number, vendor,
        device_type_fk, technology, description). Merge semantics."""
        if resp := _writes_disabled():
            return resp
        model = get_object_or_404(VendorModel, key=key)
        previous = snapshot_device(model)
        form = _merged_form(VendorModelForm, model, request.data)
        if not form.is_valid():
            return Response({"error": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        model = form.save()
        record_history(model, DeviceHistory.Action.UPDATED, _agent_user(), previous)
        return Response({"key": str(model.key), "note": DRAFT_NOTE})

    def destroy(self, request, key=None):
        if resp := _writes_disabled():
            return resp
        model = get_object_or_404(VendorModel, key=key)
        record_history(model, DeviceHistory.Action.DELETED, _agent_user())
        label = str(model)
        model.delete()
        return Response({"deleted": label, "note": DRAFT_NOTE})

    @action(detail=True, methods=["get"])
    def history(self, request, key=None):
        model = get_object_or_404(VendorModel, key=key)
        entries = model.history.order_by("-version")[:20]
        return Response({
            "key": str(model.key),
            "history": [
                {
                    "version": h.version,
                    "action": h.action,
                    "user": h.user.username if h.user else None,
                    "created_at": h.created.isoformat(),
                    "changes": h.changes,
                }
                for h in entries
            ],
        })

    @action(detail=True, methods=["put"], url_path="config/(?P<section>[a-z]+)")
    def config(self, request, key=None, section=None):
        """Edit one config section (processor/alarm/modbus/wmbus/lorawan/
        control) through the same form the UI uses. Merge semantics."""
        if resp := _writes_disabled():
            return resp
        if section not in CONFIG_SECTIONS:
            return Response(
                {"error": f"Unknown section '{section}'. One of: {', '.join(CONFIG_SECTIONS)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        model = get_object_or_404(VendorModel, key=key)
        previous = snapshot_device(model)

        form_class, accessor = CONFIG_SECTIONS[section]
        instance = getattr(model, accessor, None)
        kwargs = {"vendor_model": model} if section == "processor" else {}
        form = _merged_form(form_class, instance, request.data, **kwargs)
        if not form.is_valid():
            return Response({"error": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        config = form.save(commit=False)
        config.device_type = model
        config.save()
        form.save_m2m()

        record_history(model, DeviceHistory.Action.UPDATED, _agent_user(), previous)
        return Response({
            "key": str(model.key),
            section: model_to_dict(config, exclude=["id", "device_type"]),
            "note": DRAFT_NOTE,
        })

    @action(detail=True, methods=["post", "put", "delete"],
            url_path="registers(?:/(?P<register_id>[0-9a-f-]+))?")
    def registers(self, request, key=None, register_id=None):
        """Modbus register CRUD. POST creates, PUT edits (merge), DELETE
        removes. Each change records a device history entry, like the UI."""
        if resp := _writes_disabled():
            return resp
        model = get_object_or_404(VendorModel, key=key)
        modbus = getattr(model, "modbus_config", None)
        if modbus is None:
            return Response(
                {"error": "Model has no modbus config — set config/modbus first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        previous = snapshot_device(model)

        if request.method == "DELETE":
            reg = get_object_or_404(RegisterDefinition, pk=register_id, modbus_config=modbus)
            label = str(reg)
            reg.delete()
            record_history(model, DeviceHistory.Action.UPDATED, _agent_user(), previous)
            return Response({"deleted": label, "note": DRAFT_NOTE})

        instance = None
        if request.method == "PUT":
            instance = get_object_or_404(RegisterDefinition, pk=register_id, modbus_config=modbus)
        form = _merged_form(RegisterDefinitionForm, instance, request.data)
        if not form.is_valid():
            return Response({"error": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        reg = form.save(commit=False)
        reg.modbus_config = modbus
        reg.save()
        record_history(model, DeviceHistory.Action.UPDATED, _agent_user(), previous)
        return Response({
            "id": str(reg.id),
            "register": model_to_dict(reg, exclude=["id", "modbus_config"]),
            "note": DRAFT_NOTE,
        })


class AgentCatalogViewSet(viewsets.ViewSet):
    """L1/L2 catalogue CRUD: vendors, metrics, device_types, alarms.

    Metric and DeviceType writes record their history tables (as the UI
    does); a DeviceType code rename propagates to every VendorModel
    mirroring the code, mirroring the UI's rename propagation.
    """

    permission_classes = [HasAPIKey]

    def _resolve(self, kind):
        if kind not in CATALOG:
            return None, Response(
                {"error": f"Unknown catalog '{kind}'. One of: {', '.join(CATALOG)}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return CATALOG[kind], None

    def list(self, request, kind=None):
        entry, err = self._resolve(kind)
        if err:
            return err
        model_class, _ = entry
        qs = model_class.objects.all()
        q = request.query_params.get("q")
        if q:
            fields = [f.name for f in model_class._meta.get_fields()
                      if f.concrete and f.get_internal_type() in ("CharField", "TextField")]
            cond = Q()
            for f in fields:
                cond |= Q(**{f"{f}__icontains": q})
            qs = qs.filter(cond)
        return Response({
            "count": qs.count(),
            "items": [
                {"id": str(obj.pk), **model_to_dict(obj, exclude=["id"])}
                for obj in qs[:200]
            ],
            "truncated": qs.count() > 200,
        })

    def _record(self, kind, obj, action_name, previous=None):
        user = _agent_user()
        if kind == "metrics":
            record_metric_history(obj, getattr(MetricHistory.Action, action_name), user, previous)
        elif kind == "device_types":
            record_device_type_history(obj, getattr(DeviceTypeHistory.Action, action_name), user, previous)

    def create(self, request, kind=None):
        if resp := _writes_disabled():
            return resp
        entry, err = self._resolve(kind)
        if err:
            return err
        _, form_class = entry
        form = form_class(data=request.data)
        if not form.is_valid():
            return Response({"error": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        obj = form.save()
        self._record(kind, obj, "CREATED")
        return Response({"id": str(obj.pk), "note": DRAFT_NOTE}, status=status.HTTP_201_CREATED)

    def update(self, request, kind=None, pk=None):
        if resp := _writes_disabled():
            return resp
        entry, err = self._resolve(kind)
        if err:
            return err
        model_class, form_class = entry
        obj = get_object_or_404(model_class, pk=pk)
        previous = None
        if kind == "metrics":
            previous = snapshot_metric(obj)
        elif kind == "device_types":
            previous = snapshot_device_type(obj)
        form = _merged_form(form_class, obj, request.data)
        if not form.is_valid():
            return Response({"error": form.errors}, status=status.HTTP_400_BAD_REQUEST)
        obj = form.save()
        self._record(kind, obj, "UPDATED", previous)
        propagated = 0
        if kind == "device_types":
            propagated = self._propagate_code_rename(obj, previous)
        payload = {"id": str(obj.pk), "note": DRAFT_NOTE}
        if propagated:
            payload["models_updated_by_code_rename"] = propagated
        return Response(payload)

    def destroy(self, request, kind=None, pk=None):
        if resp := _writes_disabled():
            return resp
        entry, err = self._resolve(kind)
        if err:
            return err
        model_class, _ = entry
        obj = get_object_or_404(model_class, pk=pk)
        self._record(kind, obj, "DELETED")
        label = str(obj)
        obj.delete()
        return Response({"deleted": label, "note": DRAFT_NOTE})

    def _propagate_code_rename(self, device_type, previous_snapshot) -> int:
        """A DeviceType code rename must reach every VendorModel mirroring
        it — same reason and mechanics as the UI's rename propagation:
        without it, renamed types keep exporting models under the old code
        and Spark can no longer join them to the L2 profile."""
        old_code = (previous_snapshot or {}).get("code")
        if not old_code or old_code == device_type.code:
            return 0
        affected = VendorModel.objects.filter(
            Q(device_type_fk=device_type) | Q(device_type=old_code),
        )
        user = _agent_user()
        for vm in affected:
            old_vm_snapshot = snapshot_device(vm)
            if not vm.device_type_fk_id:
                vm.device_type_fk = device_type
            vm.save()
            record_history(vm, DeviceHistory.Action.UPDATED, user, old_vm_snapshot)
        return affected.count()


class AgentStatusViewSet(viewsets.ViewSet):
    """Library-wide state: current version + unpublished drafts."""

    permission_classes = [HasAPIKey]

    def list(self, request):
        current = LibraryVersion.objects.filter(is_current=True).first()
        summary = unpublished_changes_summary()
        return Response({
            "current_version": {
                "version": current.version,
                "released_at": current.released_at.isoformat(),
                "published_by": current.published_by.username if current and current.published_by else None,
            } if current else None,
            "writes_enabled": settings.AGENT_API_ALLOW_WRITES,
            "unpublished": asdict(summary),
        })
