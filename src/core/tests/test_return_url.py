"""Return to the originating page after create/edit/delete (core.return_url)."""

from urllib.parse import quote

import pytest
from django.test import RequestFactory

from core.models import User
from core.return_url import get_next_url
from library.models import APIKey, DeviceType, GatewayAssignment, Vendor, VendorModel

pytestmark = pytest.mark.django_db


def _next(path):
    return quote(path, safe="")


@pytest.fixture
def editor_client(client):
    client.force_login(User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR))
    return client


@pytest.fixture
def admin_client(client):
    client.force_login(User.objects.create_user(username="ad", password="x", role=User.Role.ADMIN))
    return client


@pytest.fixture
def gateway():
    return GatewayAssignment.objects.create(serial_number="GW-1", name="Roof")


@pytest.fixture
def model():
    device_type, _ = DeviceType.objects.get_or_create(code="power_meter", defaults={"label": "Power Meter"})
    vendor = Vendor.objects.create(name="Acme", slug="acme")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="PM1",
        name="Power Meter 1",
        device_type_fk=device_type,
        technology=VendorModel.Technology.MODBUS,
    )


# --- get_next_url -----------------------------------------------------------


@pytest.mark.parametrize(
    ("next_value", "expected"),
    [
        ("/gateways/?q=roof", "/gateways/?q=roof"),
        ("https://evil.example/", None),
        ("//evil.example/", None),
        ("javascript:alert(1)", None),
        ("", None),
    ],
)
def test_get_next_url_accepts_only_local_urls(next_value, expected):
    request = RequestFactory().get("/", {"next": next_value})
    assert get_next_url(request) == expected


def test_get_next_url_prefers_post_over_get():
    request = RequestFactory().post("/?next=/from-get/", {"next": "/from-post/"})
    assert get_next_url(request) == "/from-post/"


def test_excluded_next_falls_back_to_its_own_next():
    detail = f"/models/1/?next={_next('/models/?vendor=acme')}"
    request = RequestFactory().post("/", {"next": detail})
    assert get_next_url(request, exclude_prefix="/models/1/") == "/models/?vendor=acme"


def test_excluded_next_without_origin_is_none():
    request = RequestFactory().post("/", {"next": "/models/1/"})
    assert get_next_url(request, exclude_prefix="/models/1/") is None


# --- views ------------------------------------------------------------------


def test_edit_without_next_keeps_default_redirect(editor_client, gateway):
    response = editor_client.post(f"/gateways/{gateway.pk}/edit/", {"serial_number": "GW-1", "name": "Roof 2"})
    assert response.url == "/gateways/"


def test_edit_with_next_returns_to_it(editor_client, gateway):
    response = editor_client.post(
        f"/gateways/{gateway.pk}/edit/?next={_next('/gateways/?q=roof&sort=-name')}",
        {"serial_number": "GW-1", "name": "Roof 2"},
    )
    assert response.url == "/gateways/?q=roof&sort=-name"


def test_edit_ignores_external_next(editor_client, gateway):
    response = editor_client.post(
        f"/gateways/{gateway.pk}/edit/", {"serial_number": "GW-1", "name": "Roof 2", "next": "https://evil.example/"}
    )
    assert response.url == "/gateways/"


def test_form_rerender_keeps_next(editor_client, gateway):
    response = editor_client.post(
        f"/gateways/{gateway.pk}/edit/", {"serial_number": "", "next": "/gateways/?q=roof"}
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert '<input type="hidden" name="next" value="/gateways/?q=roof">' in html
    assert 'href="/gateways/?q=roof"' in html  # Cancel


def test_delete_returns_to_next(editor_client, gateway):
    response = editor_client.post(f"/gateways/{gateway.pk}/delete/?next={_next('/gateways/?q=roof')}")
    assert response.url == "/gateways/?q=roof"


def test_delete_from_detail_returns_to_where_detail_was_opened(editor_client, model):
    detail = f"/models/{model.pk}/?next={_next('/models/?vendor=acme')}"
    response = editor_client.post(f"/models/{model.pk}/delete/?next={_next(detail)}")
    assert response.url == "/models/?vendor=acme"
    assert not VendorModel.objects.filter(pk=model.pk).exists()


def test_delete_from_detail_without_origin_goes_to_list(editor_client, model):
    response = editor_client.post(f"/models/{model.pk}/delete/?next={_next(f'/models/{model.pk}/')}")
    assert response.url == "/models/"


def test_apikey_revoke_from_list_stays_on_list(admin_client):
    apikey = APIKey.objects.create(name="spark")
    response = admin_client.post(f"/api-keys/{apikey.pk}/revoke/?next={_next('/api-keys/')}")
    assert response.url == "/api-keys/"


@pytest.fixture
def admin_pages(model, gateway):
    """Every form/confirm page that posts ``next`` back, keyed by path."""
    from library.models import Alarm, Metric, ModbusConfig, RegisterDefinition

    metric = Metric.objects.create(key="x:power", label="Power", data_type="decimal")
    alarm = Alarm.objects.create(key="x:leak", label="Leak", default_severity="critical")
    config, _ = ModbusConfig.objects.get_or_create(device_type=model)
    register = RegisterDefinition.objects.create(modbus_config=config, field_name="power", address=1, data_type="uint16")
    m = model.pk
    return [
        "/metrics/create/",
        f"/metrics/{metric.pk}/edit/",
        f"/metrics/{metric.pk}/delete/",
        "/alarms/create/",
        f"/alarms/{alarm.pk}/edit/",
        f"/alarms/{alarm.pk}/delete/",
        "/gateways/create/",
        f"/gateways/{gateway.pk}/edit/",
        f"/device-types/{model.device_type_fk.pk}/edit/",
        f"/models/{m}/edit/",
        f"/models/{m}/modbus-config/edit/",
        f"/models/{m}/control-config/edit/",
        f"/models/{m}/wmbus-config/edit/",
        f"/models/{m}/lorawan-config/edit/",
        f"/models/{m}/processor-config/edit/",
        f"/models/{m}/alarm-config/edit/",
        f"/models/{m}/provisioning/edit/",
        f"/models/{m}/registers/create/",
        f"/models/{m}/registers/{register.pk}/edit/",
        f"/models/{m}/procedure/edit/",
    ]


def test_form_pages_post_next_back_and_cancel_to_it(admin_client, admin_pages):
    for path in admin_pages:
        response = admin_client.get(f"{path}?next={_next('/origin/?q=1')}")
        assert response.status_code == 200, path
        html = response.content.decode()
        assert '<input type="hidden" name="next" value="/origin/?q=1">' in html, path
        assert 'href="/origin/?q=1"' in html, path


@pytest.mark.parametrize(
    "path", ["/metrics/", "/alarms/", "/gateways/", "/api-keys/", "/models/", "/wmbus-mappings/", "/vendors/acme/"]
)
def test_pages_with_next_links_render(admin_client, model, gateway, path):
    assert admin_client.get(path).status_code == 200


def test_list_links_carry_the_current_page(editor_client, gateway):
    html = editor_client.get("/gateways/?q=roof").content.decode()
    assert f"/gateways/{gateway.pk}/edit/?next={_next('/gateways/?q=roof')}" in html
