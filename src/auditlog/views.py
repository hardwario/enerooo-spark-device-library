"""Audit log views."""

from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.views.generic import ListView

from .models import AuditLog

User = get_user_model()


class AuditLogListView(LoginRequiredMixin, ListView):
    """Activity log with filtering."""

    model = AuditLog
    template_name = "auditlog/log_list.html"
    context_object_name = "logs"
    paginate_by = 50

    def get_queryset(self):
        queryset = super().get_queryset().select_related("user")

        category = self.request.GET.get("category")
        user_id = self.request.GET.get("user")
        date_from = self.request.GET.get("date_from")
        date_to = self.request.GET.get("date_to")
        search = self.request.GET.get("q")

        if category:
            queryset = queryset.filter(category=category)
        if user_id:
            queryset = queryset.filter(user_id=user_id)
        if date_from:
            queryset = queryset.filter(created__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(created__date__lte=date_to)
        if search:
            queryset = queryset.filter(
                Q(target_label__icontains=search) | Q(action__icontains=search) | Q(user__username__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["category_choices"] = AuditLog.Category.choices
        context["current_category"] = self.request.GET.get("category", "")
        context["users"] = User.objects.filter(audit_logs__isnull=False).distinct().order_by("username")
        context["current_user_id"] = self.request.GET.get("user", "")
        context["date_from"] = self.request.GET.get("date_from", "")
        context["date_to"] = self.request.GET.get("date_to", "")
        context["search_query"] = self.request.GET.get("q", "")
        return context
