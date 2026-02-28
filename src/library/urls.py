"""Library URL configuration."""

from django.urls import path

from . import views

app_name = "library"

urlpatterns = [
    # Dashboard
    path("", views.DashboardView.as_view(), name="dashboard"),
    # Vendors
    path("vendors/", views.VendorListView.as_view(), name="vendor-list"),
    path("vendors/<slug:slug>/", views.VendorDetailView.as_view(), name="vendor-detail"),
    # Devices
    path("devices/", views.DeviceTypeListView.as_view(), name="device-list"),
    path("devices/create/", views.DeviceTypeCreateView.as_view(), name="device-create"),
    path("devices/<uuid:pk>/", views.DeviceTypeDetailView.as_view(), name="device-detail"),
    path("devices/<uuid:pk>/edit/", views.DeviceTypeUpdateView.as_view(), name="device-edit"),
    path("devices/<uuid:pk>/delete/", views.DeviceTypeDeleteView.as_view(), name="device-delete"),
    # Registers (for Modbus devices)
    path("devices/<uuid:device_pk>/registers/", views.RegisterListView.as_view(), name="register-list"),
    path(
        "devices/<uuid:device_pk>/registers/create/",
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
    # API Keys
    path("api-keys/", views.APIKeyListView.as_view(), name="apikey-list"),
    path("api-keys/create/", views.APIKeyCreateView.as_view(), name="apikey-create"),
    path("api-keys/<uuid:pk>/revoke/", views.APIKeyRevokeView.as_view(), name="apikey-revoke"),
]
