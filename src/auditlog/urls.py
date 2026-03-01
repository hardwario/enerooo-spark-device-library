"""Audit log URL configuration."""

from django.urls import path

from . import views

app_name = "auditlog"

urlpatterns = [
    path("activity/", views.AuditLogListView.as_view(), name="log-list"),
]
