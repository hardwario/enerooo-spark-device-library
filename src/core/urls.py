"""Core URL configuration."""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    # User management (admin only)
    path("users/", views.UserListView.as_view(), name="user-list"),
    path("users/<uuid:pk>/role/", views.UserUpdateRoleView.as_view(), name="user-role"),
    # Invitations
    path("invitations/", views.InvitationListView.as_view(), name="invitation-list"),
    path("invitations/create/", views.InvitationCreateView.as_view(), name="invitation-create"),
    path("invitations/<uuid:pk>/revoke/", views.InvitationRevokeView.as_view(), name="invitation-revoke"),
    path("invitations/<uuid:pk>/resend/", views.InvitationResendView.as_view(), name="invitation-resend"),
    path("invite/<str:token>/", views.AcceptInvitationView.as_view(), name="accept-invitation"),
]
