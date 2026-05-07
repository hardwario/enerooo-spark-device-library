"""API viewsets for the device library."""

import hashlib

from django.db.models import Count, Max
from django.utils.http import http_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from library.exporters import snapshot_to_schema
from library.models import DEFAULT_SCHEMA_VERSION, APIKey, DeviceHistory, DeviceType, GatewayAssignment, LibraryVersion, LibraryVersionDevice, Vendor, VendorModel

from .permissions import HasAPIKey, HasServiceToken, IsAPIKeyOrSessionAuth, IsEditorOrAdmin
from .serializers import (
    APIKeySerializer,
    DeviceTypeSerializer,
    GatewayAssignmentSerializer,
    LibraryVersionSerializer,
    ManifestSerializer,
    VendorAdminSerializer,
    VendorModelAdminSerializer,
    VendorModelDetailSerializer,
    VendorModelListSerializer,
    VendorSerializer,
    VendorWithDevicesSerializer,
)


# === Sync API viewsets (read-only, API key auth) ===


class ManifestViewSet(viewsets.ViewSet):
    """Current library manifest / version info."""

    permission_classes = [IsAPIKeyOrSessionAuth]

    def list(self, request):
        current = LibraryVersion.objects.filter(is_current=True).first()
        data = {
            "version": current.version if current else "0.0.0",
            "schema_version": current.schema_version if current else DEFAULT_SCHEMA_VERSION,
            "vendor_count": Vendor.objects.count(),
            "device_count": VendorModel.objects.count(),
            "device_type_count": DeviceType.objects.count(),
        }
        serializer = ManifestSerializer(data)

        response = Response(serializer.data)

        # ETag support
        etag = hashlib.md5(str(data).encode()).hexdigest()
        response["ETag"] = f'"{etag}"'

        if_none_match = request.headers.get("If-None-Match", "")
        if if_none_match == f'"{etag}"':
            return Response(status=status.HTTP_304_NOT_MODIFIED)

        return response


class SyncVendorViewSet(viewsets.ReadOnlyModelViewSet):
    """Vendors with device counts for sync."""

    permission_classes = [IsAPIKeyOrSessionAuth]
    serializer_class = VendorSerializer

    def get_queryset(self):
        return Vendor.objects.annotate(device_count=Count("device_types"))


class SyncDeviceViewSet(viewsets.ReadOnlyModelViewSet):
    """Device types for sync — supports filtering."""

    permission_classes = [IsAPIKeyOrSessionAuth]
    filterset_fields = ["vendor__slug", "technology", "device_type"]
    search_fields = ["name", "model_number"]

    def get_serializer_class(self):
        if self.action == "retrieve":
            return VendorModelDetailSerializer
        return VendorModelListSerializer

    def get_queryset(self):
        qs = VendorModel.objects.select_related(
            "vendor",
            "modbus_config",
            "lorawan_config",
            "wmbus_config",
            "control_config",
            "processor_config",
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("modbus_config__register_definitions")
        return qs


class SyncViewSet(viewsets.ViewSet):
    """Full sync payload — all vendors + devices + configs."""

    permission_classes = [IsAPIKeyOrSessionAuth]

    def list(self, request):
        # Check ETag / If-Modified-Since
        last_modified = VendorModel.objects.aggregate(last=Max("modified"))["last"]

        if last_modified:
            etag = hashlib.md5(str(last_modified).encode()).hexdigest()
            if_none_match = request.headers.get("If-None-Match", "")
            if if_none_match == f'"{etag}"':
                return Response(status=status.HTTP_304_NOT_MODIFIED)

        vendors = Vendor.objects.prefetch_related(
            "device_types__modbus_config__register_definitions",
            "device_types__lorawan_config",
            "device_types__wmbus_config",
            "device_types__control_config",
            "device_types__processor_config",
        ).all()

        current = LibraryVersion.objects.filter(is_current=True).first()

        data = {
            "version": current.version if current else "0.0.0",
            "schema_version": current.schema_version if current else DEFAULT_SCHEMA_VERSION,
            "device_types": DeviceTypeSerializer(DeviceType.objects.all(), many=True).data,
            "vendors": VendorWithDevicesSerializer(vendors, many=True).data,
        }

        response = Response(data)
        if last_modified:
            response["ETag"] = f'"{etag}"'
            response["Last-Modified"] = http_date(last_modified.timestamp())
        return response


# === Token-authenticated library sync endpoints ===


def _update_gateway_last_seen(request):
    """Update last_seen for the gateway identified by X-Gateway-Serial header."""
    serial = request.headers.get("X-Gateway-Serial", "")
    if serial:
        from django.utils import timezone as tz

        GatewayAssignment.objects.filter(serial_number=serial).update(last_seen=tz.now())


class LibraryVersionSyncViewSet(viewsets.ViewSet):
    """Current library version for cheap polling."""

    permission_classes = [HasServiceToken]

    def list(self, request):
        _update_gateway_last_seen(request)
        current = LibraryVersion.objects.filter(is_current=True).first()
        return Response({"version": current.version if current else 0})


class LibraryContentViewSet(viewsets.ViewSet):
    """Full library content for a specific version."""

    permission_classes = [HasServiceToken]

    def retrieve(self, request, pk=None):
        _update_gateway_last_seen(request)
        try:
            lib_version = LibraryVersion.objects.get(version=int(pk))
        except (LibraryVersion.DoesNotExist, ValueError, TypeError):
            return Response(
                {"detail": "Version not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        entries = lib_version.device_changes.exclude(
            change_type=LibraryVersionDevice.ChangeType.REMOVED,
        )

        # Batch-fetch all relevant DeviceHistory snapshots
        history_lookup = {}
        for entry in entries:
            if entry.device_type_id:
                snapshot = (
                    DeviceHistory.objects.filter(
                        device_id=entry.device_type_id,
                        version=entry.device_version,
                    )
                    .values_list("snapshot", flat=True)
                    .first()
                )
                if snapshot:
                    history_lookup[entry.device_type_id] = snapshot

        # Group devices by vendor
        vendors = {}
        for entry in entries:
            snap = history_lookup.get(entry.device_type_id)
            if not snap:
                continue
            vendor_name = snap.get("vendor", "Unknown")
            vendor_key = snap.get("vendor_key", "")
            if vendor_name not in vendors:
                vendors[vendor_name] = {"key": vendor_key, "models": []}
            vendors[vendor_name]["models"].append(snapshot_to_schema(snap))

        vendor_list = [
            {"key": info["key"], "name": name, "models": info["models"]}
            for name, info in sorted(vendors.items())
        ]

        return Response({
            "version": lib_version.version,
            "schema_version": lib_version.schema_version,
            "device_types": DeviceTypeSerializer(DeviceType.objects.all(), many=True).data,
            "vendors": vendor_list,
        })


class SyncDeviceTypeViewSet(viewsets.ReadOnlyModelViewSet):
    """Schema-v3 device type catalogue (read-only, sync-auth)."""

    permission_classes = [IsAPIKeyOrSessionAuth]
    serializer_class = DeviceTypeSerializer
    queryset = DeviceType.objects.all()
    lookup_field = "code"


# === Gateway Bootstrap ===


class GatewayBootstrapViewSet(viewsets.ViewSet):
    """POST /api/v1/bootstrap/ — register a gateway and return its Spark URL.

    Creates the GatewayAssignment if it doesn't exist (with empty spark_url).
    Returns {"serial_number": "...", "spark_url": "...", "assigned": true/false}.
    Authenticated via shared service token (X-Service-Token header).
    """

    permission_classes = [HasServiceToken]

    def create(self, request, *args, **kwargs):
        serial = request.data.get("serial_number")
        if not serial:
            return Response(
                {"detail": "serial_number is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone as tz

        now = tz.now()
        obj, created = GatewayAssignment.objects.get_or_create(
            serial_number=serial,
            defaults={"spark_url": "", "assigned_by": "", "is_registered": True, "registered_at": now, "last_seen": now},
        )
        if not created:
            update_fields = ["last_seen"]
            obj.last_seen = now
            if not obj.is_registered:
                obj.is_registered = True
                obj.registered_at = now
                update_fields += ["is_registered", "registered_at"]
            obj.save(update_fields=update_fields)

        return Response({
            "serial_number": obj.serial_number,
            "spark_url": obj.spark_url,
            "is_registered": obj.is_registered,
            "is_assigned": obj.is_assigned,
        })


class GatewayAssignmentViewSet(mixins.CreateModelMixin, mixins.DestroyModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """POST /api/v1/assignments/ — upsert a gateway assignment.
    DELETE /api/v1/assignments/<serial>/ — unassign a gateway.
    """

    permission_classes = [HasServiceToken]
    serializer_class = GatewayAssignmentSerializer
    lookup_field = "serial_number"
    queryset = GatewayAssignment.objects.all()

    def create(self, request, *args, **kwargs):
        serial = request.data.get("serial_number")
        spark_url = request.data.get("spark_url")
        assigned_by = request.data.get("assigned_by", "")

        if not serial or not spark_url:
            return Response(
                {"detail": "serial_number and spark_url are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.utils import timezone as tz

        obj, created = GatewayAssignment.objects.update_or_create(
            serial_number=serial,
            defaults={
                "spark_url": spark_url,
                "assigned_by": assigned_by,
                "is_assigned": True,
                "assigned_at": tz.now(),
            },
        )
        serializer = self.get_serializer(obj)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


# === Admin API viewsets (CRUD, session auth) ===


class AdminVendorViewSet(viewsets.ModelViewSet):
    """CRUD for vendors (admin)."""

    permission_classes = [IsEditorOrAdmin]
    serializer_class = VendorAdminSerializer
    queryset = Vendor.objects.all()


class AdminVendorModelViewSet(viewsets.ModelViewSet):
    """CRUD for vendor models (admin)."""

    permission_classes = [IsEditorOrAdmin]
    serializer_class = VendorModelAdminSerializer
    queryset = VendorModel.objects.select_related("vendor").all()
    filterset_fields = ["vendor", "technology", "device_type"]


class AdminVersionViewSet(viewsets.ReadOnlyModelViewSet):
    """View library versions (admin)."""

    permission_classes = [IsEditorOrAdmin]
    serializer_class = LibraryVersionSerializer
    queryset = LibraryVersion.objects.prefetch_related("device_changes__device_type").all()


class AdminAPIKeyViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Manage API keys (admin)."""

    permission_classes = [IsEditorOrAdmin]
    serializer_class = APIKeySerializer
    queryset = APIKey.objects.all()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        key = self.get_object()
        key.is_active = False
        key.save(update_fields=["is_active"])
        return Response({"status": "revoked"})
