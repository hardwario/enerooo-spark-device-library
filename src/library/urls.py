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
    path("models/", views.DeviceTypeListView.as_view(), name="model-list"),
    path("models/create/", views.DeviceTypeCreateView.as_view(), name="model-create"),
    path("models/<uuid:pk>/", views.DeviceTypeDetailView.as_view(), name="model-detail"),
    path("models/<uuid:pk>/edit/", views.DeviceTypeUpdateView.as_view(), name="model-edit"),
    path("models/<uuid:pk>/delete/", views.DeviceTypeDeleteView.as_view(), name="model-delete"),
    path("models/<uuid:pk>/history/<int:version>/", views.DeviceHistorySnapshotView.as_view(), name="model-history-snapshot"),
    path("models/<uuid:pk>/history/diff/", views.DeviceHistoryDiffView.as_view(), name="model-history-diff"),
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
    # Versions
    path("versions/", views.VersionListView.as_view(), name="version-list"),
    path("versions/create/", views.VersionCreateView.as_view(), name="version-create"),
    path("versions/<uuid:pk>/", views.VersionDetailView.as_view(), name="version-detail"),
    path("versions/<uuid:pk>/export/", views.VersionExportView.as_view(), name="version-export"),
    # API Keys
    path("api-keys/", views.APIKeyListView.as_view(), name="apikey-list"),
    path("api-keys/create/", views.APIKeyCreateView.as_view(), name="apikey-create"),
    path("api-keys/<uuid:pk>/revoke/", views.APIKeyRevokeView.as_view(), name="apikey-revoke"),
]
