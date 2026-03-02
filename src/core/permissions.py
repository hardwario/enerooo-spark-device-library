"""Role-based permission mixins."""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied

from .models import User


class RoleRequiredMixin(LoginRequiredMixin):
    """Mixin that requires a minimum role level."""

    required_role = User.Role.VIEWER

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        if hasattr(request, "user") and request.user.is_authenticated:
            if not request.user.has_role(self.required_role):
                raise PermissionDenied
        return response


class SuperuserRequiredMixin(LoginRequiredMixin):
    """Mixin that requires the user to be a superuser."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
