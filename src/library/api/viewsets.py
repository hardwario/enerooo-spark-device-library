"""API viewsets for the device library."""

import hashlib

from django.db.models import Count, Max
from django.utils.http import http_date
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from library.models import APIKey, DeviceType, LibraryVersion, Vendor

from .permissions import HasAPIKey, IsAPIKeyOrSessionAuth, IsEditorOrAdmin
from .serializers import (
    APIKeySerializer,
    DeviceTypeAdminSerializer,
    DeviceTypeDetailSerializer,
    DeviceTypeListSerializer,
    LibraryVersionSerializer,
    ManifestSerializer,
    VendorAdminSerializer,
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
            "schema_version": current.schema_version if current else 2,
            "vendor_count": Vendor.objects.count(),
            "device_count": DeviceType.objects.count(),
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
            return DeviceTypeDetailSerializer
        return DeviceTypeListSerializer

    def get_queryset(self):
        qs = DeviceType.objects.select_related(
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
        last_modified = DeviceType.objects.aggregate(last=Max("modified"))["last"]

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
            "schema_version": current.schema_version if current else 2,
            "vendors": VendorWithDevicesSerializer(vendors, many=True).data,
        }

        response = Response(data)
        if last_modified:
            response["ETag"] = f'"{etag}"'
            response["Last-Modified"] = http_date(last_modified.timestamp())
        return response


# === Admin API viewsets (CRUD, session auth) ===


class AdminVendorViewSet(viewsets.ModelViewSet):
    """CRUD for vendors (admin)."""

    permission_classes = [IsEditorOrAdmin]
    serializer_class = VendorAdminSerializer
    queryset = Vendor.objects.all()


class AdminDeviceTypeViewSet(viewsets.ModelViewSet):
    """CRUD for device types (admin)."""

    permission_classes = [IsEditorOrAdmin]
    serializer_class = DeviceTypeAdminSerializer
    queryset = DeviceType.objects.select_related("vendor").all()
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
