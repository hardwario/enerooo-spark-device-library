"""Sidebar nav: section highlighting and role-gated items."""

import re

import pytest
from django.urls import URLResolver, get_resolver

from core.models import User
from core.navigation import NAV_SECTIONS
from library.models import DeviceType, Vendor, VendorModel

APP_NAMESPACES = {"library", "core", "auditlog"}


def _named_urls(resolver, namespace=None):
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            yield from _named_urls(pattern, pattern.namespace or namespace)
        elif pattern.name and namespace in APP_NAMESPACES:
            yield f"{namespace}:{pattern.name}"


def _active_nav_hrefs(html):
    return re.findall(r'class="nav-link active" href="([^"]+)"', html)


@pytest.fixture
def modbus_model(db):
    device_type, _ = DeviceType.objects.get_or_create(code="power_meter", defaults={"label": "Power Meter"})
    vendor = Vendor.objects.create(name="Acme", slug="acme")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="PM1",
        name="Power Meter 1",
        device_type_fk=device_type,
        technology=VendorModel.Technology.MODBUS,
    )


@pytest.fixture
def editor(db):
    return User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR)


def test_every_app_url_has_a_nav_section():
    missing = sorted(set(_named_urls(get_resolver())) - set(NAV_SECTIONS))
    assert missing == [], f"Add these URL names to core/navigation.py: {missing}"


def test_nav_sections_has_no_stale_entries():
    stale = sorted(set(NAV_SECTIONS) - set(_named_urls(get_resolver())))
    assert stale == []


@pytest.mark.parametrize("path", ["modbus-config/edit/", "alarm-config/edit/", "provisioning/edit/", "documentation/"])
def test_model_subpages_highlight_models(client, editor, modbus_model, path):
    client.force_login(editor)
    response = client.get(f"/models/{modbus_model.pk}/{path}")
    assert response.status_code == 200
    assert _active_nav_hrefs(response.content.decode()) == ["/models/"]


def test_list_page_highlights_its_own_section(client, editor):
    client.force_login(editor)
    response = client.get("/alarms/")
    assert _active_nav_hrefs(response.content.decode()) == ["/alarms/"]


@pytest.mark.parametrize(("role", "visible"), [(User.Role.VIEWER, False), (User.Role.EDITOR, False), (User.Role.ADMIN, True)])
def test_users_and_invitations_only_shown_to_admins(client, db, role, visible):
    client.force_login(User.objects.create_user(username="u", password="x", role=role))
    html = client.get("/").content.decode()
    assert ('href="/users/"' in html) is visible
    assert ('href="/invitations/"' in html) is visible
