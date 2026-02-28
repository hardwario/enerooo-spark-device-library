"""API URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .viewsets import (
    AdminAPIKeyViewSet,
    AdminDeviceTypeViewSet,
    AdminVendorViewSet,
    AdminVersionViewSet,
    ManifestViewSet,
    SyncDeviceViewSet,
    SyncVendorViewSet,
    SyncViewSet,
)

router = DefaultRouter()

# Sync API (API key auth)
router.register("manifest", ManifestViewSet, basename="manifest")
router.register("vendors", SyncVendorViewSet, basename="vendor")
router.register("devices", SyncDeviceViewSet, basename="device")
router.register("sync", SyncViewSet, basename="sync")

# Admin API (session auth)
router.register("admin/vendors", AdminVendorViewSet, basename="admin-vendor")
router.register("admin/devices", AdminDeviceTypeViewSet, basename="admin-device")
router.register("admin/versions", AdminVersionViewSet, basename="admin-version")
router.register("admin/api-keys", AdminAPIKeyViewSet, basename="admin-apikey")

urlpatterns = [
    path("", include(router.urls)),
]
