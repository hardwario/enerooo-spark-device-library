"""RoleRequiredMixin: the role is checked before the view runs."""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

from core.models import Invitation, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def invitation():
    return Invitation.objects.create(email="new@example.com", expires_at=timezone.now() + timedelta(days=7))


def test_anonymous_is_redirected_to_login(client):
    response = client.get("/vendors/create/")
    assert response.status_code == 302
    assert response.url.startswith("/login/")


def test_insufficient_role_gets_403_without_running_the_view(client, invitation):
    editor = User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR)
    client.force_login(editor)
    response = client.post(f"/invitations/{invitation.pk}/resend/")
    assert response.status_code == 403
    assert mail.outbox == []


def test_sufficient_role_runs_the_view(client, invitation):
    admin = User.objects.create_user(username="ad", password="x", role=User.Role.ADMIN)
    client.force_login(admin)
    response = client.post(f"/invitations/{invitation.pk}/resend/")
    assert response.status_code == 302
    assert len(mail.outbox) == 1
