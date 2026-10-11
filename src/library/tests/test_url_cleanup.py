"""Register URLs nested under the model, legacy redirects, Import / Export tabs."""

from urllib.parse import quote

import pytest

from core.models import User
from library.models import ModbusConfig, RegisterDefinition, Vendor, VendorModel

pytestmark = pytest.mark.django_db


@pytest.fixture
def editor_client(client):
    client.force_login(User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR))
    return client


def _modbus_model(model_number, device_type):
    vendor, _ = Vendor.objects.get_or_create(name="Acme", slug="acme")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number=model_number,
        name=model_number,
        device_type_fk=device_type,
        technology=VendorModel.Technology.MODBUS,
    )


@pytest.fixture
def model(water_meter_type):
    return _modbus_model("PM1", water_meter_type)


@pytest.fixture
def register(model):
    config, _ = ModbusConfig.objects.get_or_create(device_type=model)
    return RegisterDefinition.objects.create(modbus_config=config, field_name="power", address=1, data_type="uint16")


def test_register_edit_is_nested_under_its_model(editor_client, model, register):
    assert editor_client.get(f"/models/{model.pk}/registers/{register.pk}/edit/").status_code == 200


def test_register_under_another_model_is_404(editor_client, register, water_meter_type):
    other = _modbus_model("PM2", water_meter_type)
    assert editor_client.get(f"/models/{other.pk}/registers/{register.pk}/edit/").status_code == 404
    assert editor_client.post(f"/models/{other.pk}/registers/{register.pk}/delete/").status_code == 404
    assert RegisterDefinition.objects.filter(pk=register.pk).exists()


def test_register_delete_is_post_only(editor_client, model, register):
    url = f"/models/{model.pk}/registers/{register.pk}/delete/"
    assert editor_client.get(url).status_code == 405
    response = editor_client.post(url)
    assert response.url == f"/models/{model.pk}/"
    assert not RegisterDefinition.objects.filter(pk=register.pk).exists()


def test_viewer_cannot_delete_register(client, model, register):
    client.force_login(User.objects.create_user(username="v", password="x", role=User.Role.VIEWER))
    assert client.post(f"/models/{model.pk}/registers/{register.pk}/delete/").status_code == 403
    assert RegisterDefinition.objects.filter(pk=register.pk).exists()


def test_model_page_deletes_registers_via_confirm_dialog(editor_client, model, register):
    html = editor_client.get(f"/models/{model.pk}/").content.decode()
    assert f'data-delete-url="/models/{model.pk}/registers/{register.pk}/delete/?next=' in html
    assert f"/models/{model.pk}/registers/{register.pk}/edit/?next=" in html


def test_legacy_register_edit_redirects_to_nested_path(editor_client, model, register):
    response = editor_client.get(f"/registers/{register.pk}/edit/?next={quote('/models/', safe='')}")
    assert response.url == f"/models/{model.pk}/registers/{register.pk}/edit/?next=%2Fmodels%2F"


def test_legacy_register_delete_redirects_to_the_model(editor_client, model, register):
    response = editor_client.get(f"/registers/{register.pk}/delete/")
    assert response.url == f"/models/{model.pk}/"
    assert RegisterDefinition.objects.filter(pk=register.pk).exists()


def test_register_list_stub_is_gone(editor_client, model):
    assert editor_client.get(f"/models/{model.pk}/registers/").status_code == 404


@pytest.mark.parametrize("path", ["/export/", "/import/"])
def test_import_and_export_link_to_each_other(client, path):
    client.force_login(User.objects.create_user(username="ad", password="x", role=User.Role.ADMIN))
    html = client.get(path).content.decode()
    assert 'href="/export/"' in html
    assert 'href="/import/"' in html
    assert f'href="{path}" class="px-4' in html and 'aria-current="page"' in html
    assert "Import / Export" in html
