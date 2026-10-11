"""Shared models table on vendor/device type pages, vendor edit, dashboard links."""

from urllib.parse import quote

import pytest

from core.models import User
from library.history import record_history
from library.models import DeviceHistory, Vendor, VendorModel

pytestmark = pytest.mark.django_db


def _q(path):
    return quote(path, safe="")


@pytest.fixture
def editor_client(client):
    client.force_login(User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR))
    return client


@pytest.fixture
def vendor():
    return Vendor.objects.create(name="Acme", slug="acme")


@pytest.fixture
def model(vendor, water_meter_type):
    m = VendorModel.objects.create(
        vendor=vendor,
        model_number="WM1",
        name="Water Meter 1",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
        product_code="ER123",
    )
    record_history(m, DeviceHistory.Action.CREATED, None)
    return m


def test_vendor_detail_uses_the_models_table(editor_client, vendor, model):
    html = editor_client.get("/vendors/acme/").content.decode()
    assert "ER123" in html  # columns the old vendor table lacked
    assert "v1" in html
    assert 'href="/models/?vendor=acme"' in html
    assert f"/models/{model.pk}/?next={_q('/vendors/acme/')}" in html
    assert f"/models/{model.pk}/edit/?next=" in html
    assert 'href="/vendors/acme/edit/' in html


def test_vendor_detail_without_models(editor_client, vendor):
    html = editor_client.get("/vendors/acme/").content.decode()
    assert "No models for this vendor." in html
    assert "Open in Models" not in html


def test_device_type_detail_uses_the_models_table(client, model, water_meter_type):
    client.force_login(User.objects.create_user(username="ad", password="x", role=User.Role.ADMIN))
    html = client.get(f"/device-types/{water_meter_type.pk}/").content.decode()
    assert "ER123" in html
    assert 'href="/models/?device_type=water_meter"' in html
    assert f"/models/{model.pk}/?next=" in html


def test_models_list_links_carry_the_filtered_page(editor_client, model):
    html = editor_client.get("/models/?vendor=acme").content.decode()
    assert f"/models/{model.pk}/?next={_q('/models/?vendor=acme')}" in html
    assert f"/models/{model.pk}/edit/?next={_q('/models/?vendor=acme')}" in html


def test_model_delete_button_carries_the_detail_origin(editor_client, model):
    detail = f"/models/{model.pk}/?next={_q('/models/?vendor=acme')}"
    html = editor_client.get(detail).content.decode()
    assert f"/models/{model.pk}/delete/?next={_q(detail)}" in html


# --- vendor edit --------------------------------------------------------------


def test_viewer_cannot_edit_vendor(client, vendor):
    client.force_login(User.objects.create_user(username="v", password="x", role=User.Role.VIEWER))
    assert client.get("/vendors/acme/edit/").status_code == 403


def test_vendor_edit_goes_to_detail_under_the_new_slug(editor_client, vendor):
    response = editor_client.post(
        f"/vendors/acme/edit/?next={_q('/vendors/acme/')}", {"name": "Acme Corp", "slug": "acme-corp"}
    )
    assert response.url == "/vendors/acme-corp/"
    vendor.refresh_from_db()
    assert (vendor.name, vendor.slug) == ("Acme Corp", "acme-corp")


def test_vendor_edit_returns_to_next(editor_client, vendor):
    response = editor_client.post(f"/vendors/acme/edit/?next={_q('/vendors/?sort=-name')}", {"name": "Acme", "slug": "acme"})
    assert response.url == "/vendors/?sort=-name"


def test_vendor_edit_rerender_links_to_the_saved_vendor(editor_client, vendor):
    Vendor.objects.create(name="Other", slug="other")
    response = editor_client.post("/vendors/acme/edit/", {"name": "Renamed", "slug": "other"})
    assert response.status_code == 200
    html = response.content.decode()
    assert 'href="/vendors/acme/"' in html
    assert "Edit Acme" in html


# --- dashboard ---------------------------------------------------------------


def test_dashboard_counts_link_to_lists(editor_client, model):
    html = editor_client.get("/").content.decode()
    for href in ["/vendors/", "/models/", "/versions/", "/api-keys/", "/models/?technology=wmbus", "/models/?device_type=water_meter"]:
        assert f'href="{href}"' in html, href
