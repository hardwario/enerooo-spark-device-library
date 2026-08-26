"""API URL configuration."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .agent import AgentCatalogViewSet, AgentModelViewSet, AgentStatusViewSet
from .viewsets import (
    AdminAPIKeyViewSet,
    AdminVendorModelViewSet,
    AdminVendorViewSet,
    AdminVersionViewSet,
    GatewayAssignmentViewSet,
    GatewayBootstrapViewSet,
    LibraryContentViewSet,
    LibraryVersionSyncViewSet,
    ManifestViewSet,
    SyncDeviceTypeViewSet,
    SyncDeviceViewSet,
    SyncVendorViewSet,
    SyncViewSet,
)

router = DefaultRouter()

# Sync API (API key auth)
router.register("manifest", ManifestViewSet, basename="manifest")
router.register("vendors", SyncVendorViewSet, basename="vendor")
router.register("devices", SyncDeviceViewSet, basename="device")
router.register("device_types", SyncDeviceTypeViewSet, basename="device-type")
router.register("sync", SyncViewSet, basename="sync")

# Gateway bootstrap
router.register("bootstrap", GatewayBootstrapViewSet, basename="bootstrap")
router.register("assignments", GatewayAssignmentViewSet, basename="assignment")

# HMAC-authenticated library sync
router.register("library/version", LibraryVersionSyncViewSet, basename="library-version")
router.register("library/content", LibraryContentViewSet, basename="library-content")

# Agent API (API key auth; consumed by the library MCP server)
router.register("agent/models", AgentModelViewSet, basename="agent-model")
router.register("agent/status", AgentStatusViewSet, basename="agent-status")

# Admin API (session auth)
router.register("admin/vendors", AdminVendorViewSet, basename="admin-vendor")
router.register("admin/devices", AdminVendorModelViewSet, basename="admin-device")
router.register("admin/versions", AdminVersionViewSet, basename="admin-version")
router.register("admin/api-keys", AdminAPIKeyViewSet, basename="admin-apikey")

# Catalogue CRUD takes the kind as a URL kwarg, which DRF routers cannot
# express — plain paths onto the ViewSet's method map.
_catalog_list = AgentCatalogViewSet.as_view({"get": "list", "post": "create"})
_catalog_detail = AgentCatalogViewSet.as_view({"put": "update", "delete": "destroy"})

urlpatterns = [
    path("agent/catalog/<str:kind>/", _catalog_list, name="agent-catalog-list"),
    path("agent/catalog/<str:kind>/<uuid:pk>/", _catalog_detail, name="agent-catalog-detail"),
    path("", include(router.urls)),
]
