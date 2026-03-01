"""Audit log admin configuration."""

from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ["created", "user", "category", "action", "target_label", "ip_address"]
    list_filter = ["category", "action", "user"]
    search_fields = ["target_label", "action", "user__username"]
    readonly_fields = [
        "id",
        "user",
        "category",
        "action",
        "target_type",
        "target_id",
        "target_label",
        "details",
        "ip_address",
        "created",
        "modified",
    ]
    date_hierarchy = "created"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
