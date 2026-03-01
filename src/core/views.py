"""Core views."""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.core.mail import send_mail
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from auditlog.helpers import log_action

from .forms import AcceptInvitationForm, InvitationForm, ProfileForm, UserRoleForm
from .models import Invitation, User
from .permissions import RoleRequiredMixin

logger = logging.getLogger(__name__)


# Profile view


class ProfileView(RoleRequiredMixin, UpdateView):
    """Allow users to update their own profile."""

    model = User
    form_class = ProfileForm
    template_name = "core/profile.html"
    success_url = reverse_lazy("core:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        log_action(self.request, "updated_profile", self.request.user, category="user")
        messages.success(self.request, "Profile updated successfully.")
        return super().form_valid(form)


# User management views (admin only)


class UserListView(RoleRequiredMixin, ListView):
    """List all users with role information."""

    required_role = User.Role.ADMIN
    model = User
    template_name = "core/user_list.html"
    context_object_name = "users"

    def get_queryset(self):
        return User.objects.all().order_by("username")


class UserUpdateRoleView(RoleRequiredMixin, UpdateView):
    """Update a user's role and active status."""

    required_role = User.Role.ADMIN
    model = User
    form_class = UserRoleForm
    template_name = "core/user_role_form.html"
    success_url = reverse_lazy("core:user-list")

    def form_valid(self, form):
        target_user = self.get_object()

        # Prevent self-demotion
        if target_user == self.request.user:
            if form.cleaned_data["role"] != self.request.user.role:
                messages.error(self.request, "You cannot change your own role.")
                return self.form_invalid(form)
            if not form.cleaned_data["is_active"]:
                messages.error(self.request, "You cannot deactivate your own account.")
                return self.form_invalid(form)

        log_action(
            self.request,
            "updated_role",
            target_user,
            category="user",
            details={"role": form.cleaned_data["role"], "is_active": form.cleaned_data["is_active"]},
        )
        messages.success(self.request, f"Updated {target_user.username}'s role to {form.cleaned_data['role']}.")
        return super().form_valid(form)


# Invitation views


class InvitationListView(RoleRequiredMixin, ListView):
    """List all invitations."""

    required_role = User.Role.ADMIN
    model = Invitation
    template_name = "core/invitation_list.html"
    context_object_name = "invitations"

    def get_queryset(self):
        return Invitation.objects.select_related("invited_by", "accepted_by").order_by("-created")


class InvitationCreateView(RoleRequiredMixin, CreateView):
    """Create a new invitation."""

    required_role = User.Role.ADMIN
    model = Invitation
    form_class = InvitationForm
    template_name = "core/invitation_form.html"

    def get_success_url(self):
        return reverse("core:invitation-list")

    def form_valid(self, form):
        form.instance.invited_by = self.request.user
        response = super().form_valid(form)

        invite_url = self.request.build_absolute_uri(
            reverse("core:accept-invitation", kwargs={"token": self.object.token})
        )

        try:
            send_mail(
                subject=f"You've been invited to {settings.COMPANY_NAME}",
                message=(
                    f"{self.request.user.username} has invited you to join {settings.COMPANY_NAME} "
                    f"as {self.object.get_role_display()}.\n\n"
                    f"Click the link below to create your account:\n{invite_url}\n\n"
                    f"This invitation expires in 7 days."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[self.object.email],
                fail_silently=False,
            )
            messages.success(self.request, f"Invitation email sent to {self.object.email}.")
        except Exception:
            logger.exception("Failed to send invitation email to %s", self.object.email)
            messages.warning(
                self.request,
                f"Invitation created but email failed to send. Share this link manually: {invite_url}",
            )

        log_action(
            self.request,
            "created_invitation",
            self.object,
            category="user",
            details={"email": self.object.email, "role": self.object.role},
        )
        return response


class InvitationRevokeView(RoleRequiredMixin, View):
    """Revoke an invitation."""

    required_role = User.Role.ADMIN

    def post(self, request, pk):
        invitation = get_object_or_404(Invitation, pk=pk)
        if invitation.accepted_at:
            messages.error(request, "This invitation has already been accepted.")
        elif invitation.revoked:
            messages.info(request, "This invitation is already revoked.")
        else:
            invitation.revoked = True
            invitation.save(update_fields=["revoked"])
            log_action(request, "revoked_invitation", invitation, category="user")
            messages.success(request, f"Invitation for {invitation.email} has been revoked.")
        return redirect("core:invitation-list")


class InvitationResendView(RoleRequiredMixin, View):
    """Resend the invitation email."""

    required_role = User.Role.ADMIN

    def post(self, request, pk):
        invitation = get_object_or_404(Invitation, pk=pk)
        if not invitation.is_valid:
            messages.error(request, f"Cannot resend — invitation is {invitation.status}.")
            return redirect("core:invitation-list")

        invite_url = request.build_absolute_uri(reverse("core:accept-invitation", kwargs={"token": invitation.token}))
        try:
            send_mail(
                subject=f"You've been invited to {settings.COMPANY_NAME}",
                message=(
                    f"{request.user.username} has invited you to join {settings.COMPANY_NAME} "
                    f"as {invitation.get_role_display()}.\n\n"
                    f"Click the link below to create your account:\n{invite_url}\n\n"
                    f"This invitation expires on {invitation.expires_at.strftime('%b %d, %Y')}."
                ),
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[invitation.email],
                fail_silently=False,
            )
            messages.success(request, f"Invitation email resent to {invitation.email}.")
        except Exception:
            logger.exception("Failed to resend invitation email to %s", invitation.email)
            messages.error(request, f"Failed to resend email to {invitation.email}.")
        return redirect("core:invitation-list")


class AcceptInvitationView(View):
    """Accept an invitation and create a user account (public, no login required)."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            messages.info(request, "You are already logged in. Log out first to accept an invitation.")
            return redirect("library:dashboard")
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, token):
        invitation = get_object_or_404(Invitation, token=token)
        if not invitation.is_valid:
            return render(request, "core/invitation_invalid.html", {"invitation": invitation})
        form = AcceptInvitationForm()
        return render(request, "core/accept_invitation.html", {"form": form, "invitation": invitation})

    def post(self, request, token):
        invitation = get_object_or_404(Invitation, token=token)
        if not invitation.is_valid:
            return render(request, "core/invitation_invalid.html", {"invitation": invitation})

        form = AcceptInvitationForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                email=invitation.email,
                password=form.cleaned_data["password"],
                role=invitation.role,
            )
            invitation.accepted_at = timezone.now()
            invitation.accepted_by = user
            invitation.save(update_fields=["accepted_at", "accepted_by"])

            login(request, user)
            messages.success(request, f"Welcome to {settings.COMPANY_NAME}, {user.username}!")
            return redirect("library:dashboard")

        return render(request, "core/accept_invitation.html", {"form": form, "invitation": invitation})
