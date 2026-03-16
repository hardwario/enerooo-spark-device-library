"""Library URL configuration."""

from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    # Dashboard
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Vendors
    path("vendors/", views.VendorListView.as_view(), name="vendor-list"),
    path("vendors/create/", views.VendorCreateView.as_view(), name="vendor-create"),
    path("vendors/<slug:slug>/", views.VendorDetailView.as_view(), name="vendor-detail"),
    path("vendors/<slug:slug>/delete/", views.VendorDeleteView.as_view(), name="vendor-delete"),
    # Models
    path("models/", views.VendorModelListView.as_view(), name="model-list"),
    path("models/create/", views.VendorModelCreateView.as_view(), name="model-create"),
    path("models/<uuid:pk>/", views.VendorModelDetailView.as_view(), name="model-detail"),
    path("models/<uuid:pk>/edit/", views.VendorModelUpdateView.as_view(), name="model-edit"),
    path("models/<uuid:pk>/delete/", views.VendorModelDeleteView.as_view(), name="model-delete"),
    path("models/<uuid:pk>/history/<int:version>/", views.DeviceHistorySnapshotView.as_view(), name="model-history-snapshot"),
    path("models/<uuid:pk>/history/diff/", views.DeviceHistoryDiffView.as_view(), name="model-history-diff"),
    # wM-Bus Mapping Table
    path("wmbus-mappings/", views.WMBusMappingView.as_view(), name="wmbus-mappings"),
    # Modbus Config
    path(
        "models/<uuid:device_pk>/modbus-config/edit/",
        views.ModbusConfigUpdateView.as_view(),
        name="modbus-config-edit",
    ),
    # Control Config
    path(
        "models/<uuid:device_pk>/control-config/edit/",
        views.ControlConfigUpdateView.as_view(),
        name="control-config-edit",
    ),
    # wM-Bus Config
    path(
        "models/<uuid:device_pk>/wmbus-config/edit/",
        views.WMBusConfigUpdateView.as_view(),
        name="wmbus-config-edit",
    ),
    # LoRaWAN Config
    path(
        "models/<uuid:device_pk>/lorawan-config/edit/",
        views.LoRaWANConfigUpdateView.as_view(),
        name="lorawan-config-edit",
    ),
    # Registers (for Modbus models)
    path("models/<uuid:device_pk>/registers/", views.RegisterListView.as_view(), name="register-list"),
    path(
        "models/<uuid:device_pk>/registers/create/",
        views.RegisterCreateView.as_view(),
        name="register-create",
    ),
    path(
        "registers/<uuid:pk>/edit/",
        views.RegisterUpdateView.as_view(),
        name="register-edit",
    ),
    path(
        "registers/<uuid:pk>/delete/",
        views.RegisterDeleteView.as_view(),
        name="register-delete",
    ),
    # Import/Export
    path("import/", views.ImportView.as_view(), name="import"),
    path("export/", views.ExportView.as_view(), name="export"),
    path("export/download/", views.ExportDownloadView.as_view(), name="export-download"),
    # Versions
    path("versions/", views.VersionListView.as_view(), name="version-list"),
    path("versions/compare/", views.VersionCompareView.as_view(), name="version-compare"),
    path("versions/create/", views.VersionCreateView.as_view(), name="version-create"),
    path("versions/<uuid:pk>/", views.VersionDetailView.as_view(), name="version-detail"),
    path("versions/<uuid:pk>/export/", views.VersionExportView.as_view(), name="version-export"),
    # API Keys
    path("api-keys/", views.APIKeyListView.as_view(), name="apikey-list"),
    path("api-keys/create/", views.APIKeyCreateView.as_view(), name="apikey-create"),
    path("api-keys/<uuid:pk>/", views.APIKeyDetailView.as_view(), name="apikey-detail"),
    path("api-keys/<uuid:pk>/revoke/", views.APIKeyRevokeView.as_view(), name="apikey-revoke"),
    path("api-keys/<uuid:pk>/enable/", views.APIKeyEnableView.as_view(), name="apikey-enable"),
    path("api-keys/<uuid:pk>/regenerate/", views.APIKeyRegenerateView.as_view(), name="apikey-regenerate"),
    path("api-keys/<uuid:pk>/delete/", views.APIKeyDeleteView.as_view(), name="apikey-delete"),
    # Gateway Assignments
    path("gateways/", views.GatewayAssignmentListView.as_view(), name="gateway-list"),
    path("gateways/create/", views.GatewayAssignmentCreateView.as_view(), name="gateway-create"),
    path("gateways/<uuid:pk>/edit/", views.GatewayAssignmentUpdateView.as_view(), name="gateway-edit"),
    path("gateways/<uuid:pk>/delete/", views.GatewayAssignmentDeleteView.as_view(), name="gateway-delete"),
]
