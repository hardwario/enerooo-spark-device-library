"""Model documentation assets: documents, images, procedures (L2 of the Provisioning plan)."""

import time

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from library.assets import assets_payload, parse_procedure_markdown, procedure_to_markdown
from library.exporters import export_to_yaml
from library.history import record_history
from library.importers import import_from_yaml
from library.models import (
    DeviceHistory,
    LibraryVersion,
    LibraryVersionDevice,
    ModelDocument,
    ModelImage,
    ModelProcedure,
    Vendor,
    VendorModel,
)
from library.provisioning import TEMPLATES

pytestmark = pytest.mark.django_db
User = get_user_model()

PDF = b"%PDF-1.4 minimal"
PNG = b"\x89PNG\r\n\x1a\n fake"


@pytest.fixture(autouse=True)
def _media_root(settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path / "media")


@pytest.fixture
def model(water_meter_type):
    vendor = Vendor.objects.create(name="Zenner", slug="zenner")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="APZ V2",
        name="APZ V2 30°",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
        provisioning=TEMPLATES["wmbus"],
    )


@pytest.fixture
def editor_client(db):
    user = User.objects.create_user(username="ed", password="x", role=User.Role.EDITOR)
    client = APIClient()
    client.force_login(user)
    return client


@pytest.fixture
def service_client(settings):
    settings.SERVICE_TOKEN = "t0k3n"
    client = APIClient()
    client.credentials(HTTP_X_SERVICE_TOKEN="t0k3n", HTTP_X_TIMESTAMP=str(int(time.time())))
    return client


def _procedure(model, **extra):
    return ModelProcedure.objects.create(
        vendor_model=model,
        title="Oživení APZ V2",
        body="## 1. Kontrola balení\nText.\n\n## 2. Načtení štítku\n> [!TIP] Naskenujte QR.\n",
        front_matter={"duration_min": 6, "tools": ["čtečka QR"], "requires_input": ["wmbus_id"], **extra},
    )


# --- models -----------------------------------------------------------------


def test_first_image_becomes_primary_and_only_one_primary(model):
    first = ModelImage.objects.create(vendor_model=model, image=SimpleUploadedFile("a.png", PNG))
    assert first.is_primary
    second = ModelImage.objects.create(vendor_model=model, image=SimpleUploadedFile("b.png", PNG), is_primary=True)
    first.refresh_from_db()
    assert second.is_primary and not first.is_primary
    assert model.images.filter(is_primary=True).count() == 1


def test_procedure_markdown_roundtrip(model):
    procedure = _procedure(model)
    text = procedure_to_markdown(procedure)
    assert text.startswith("---\ntitle: Oživení APZ V2\n")
    front, body = parse_procedure_markdown(text)
    assert front["model_key"] == str(model.key)
    assert "language" not in front
    assert front["tools"] == ["čtečka QR"]
    assert body == procedure.body


def test_parse_markdown_without_front_matter():
    assert parse_procedure_markdown("## 1. Step") == ({}, "## 1. Step")


def test_assets_payload_shape(model):
    ModelDocument.objects.create(vendor_model=model, title="Manual", file=SimpleUploadedFile("manual.pdf", PDF))
    ModelImage.objects.create(vendor_model=model, image=SimpleUploadedFile("a.png", PNG), caption="Front")
    _procedure(model)
    payload = assets_payload(model)
    doc = payload["documents"][0]
    assert doc["title"] == "Manual" and doc["size"] == len(PDF)
    assert doc["url"] == f"/api/v1/models/{model.key}/documents/{doc['id']}/"
    assert payload["images"][0]["is_primary"] is True
    assert payload["procedure"] == {
        "version": 1, "title": "Oživení APZ V2", "url": f"/api/v1/models/{model.key}/procedure/",
    }


# --- YAML export / import -----------------------------------------------------


def test_procedures_export_and_import(tmp_path, model):
    _procedure(model)
    export_to_yaml(tmp_path / "devices")
    assert [p.name for p in (tmp_path / "procedures").glob("*.md")] == [f"{model.key}.md"]

    ModelProcedure.objects.all().delete()
    stats = import_from_yaml(tmp_path / "devices", tmp_path / "manifest.yaml")
    assert stats["procedures_imported"] == 1
    assert stats["errors"] == []
    restored = ModelProcedure.objects.get(vendor_model=model)
    assert restored.title == "Oživení APZ V2"
    assert restored.front_matter == {"duration_min": 6, "tools": ["čtečka QR"], "requires_input": ["wmbus_id"]}
    assert "## 2. Načtení štítku" in restored.body


# --- API ----------------------------------------------------------------------


def test_assets_api_requires_service_token(model):
    assert APIClient().get(f"/api/v1/models/{model.key}/assets/").status_code == 403


def test_assets_api_serves_metadata_and_files(service_client, model):
    doc = ModelDocument.objects.create(
        vendor_model=model, title="Manual", file=SimpleUploadedFile("manual.pdf", PDF),
    )
    image = ModelImage.objects.create(vendor_model=model, image=SimpleUploadedFile("a.png", PNG))
    _procedure(model)

    meta = service_client.get(f"/api/v1/models/{model.key}/assets/").json()
    assert meta["documents"][0]["id"] == str(doc.id)

    pdf = service_client.get(f"/api/v1/models/{model.key}/documents/{doc.id}/")
    assert pdf.status_code == 200 and pdf["Content-Type"] == "application/pdf"
    assert b"".join(pdf.streaming_content) == PDF

    png = service_client.get(f"/api/v1/models/{model.key}/images/{image.id}/")
    assert png.status_code == 200 and png["Content-Type"] == "image/png"

    md = service_client.get(f"/api/v1/models/{model.key}/procedure/")
    assert md.status_code == 200 and md["Content-Type"].startswith("text/markdown")
    assert md.content.decode().startswith("---\ntitle: ")


def test_published_content_carries_assets(service_client, model):
    _procedure(model)
    record_history(model, DeviceHistory.Action.CREATED, None)
    version = LibraryVersion.objects.create(version=1, is_current=True)
    LibraryVersionDevice.objects.create(
        library_version=version, device_type=model, device_version=1,
        device_label=str(model), change_type=LibraryVersionDevice.ChangeType.ADDED,
    )
    body = service_client.get("/api/v1/library/content/1/").json()
    assets = body["vendors"][0]["models"][0]["assets"]
    assert assets["documents"] == [] and assets["images"] == []
    assert assets["procedure"]["title"] == "Oživení APZ V2"


def test_devices_detail_carries_assets(model):
    user = User.objects.create_user(username="s", password="x", is_staff=True, is_superuser=True)
    client = APIClient()
    client.force_authenticate(user=user)
    detail = client.get(f"/api/v1/devices/{model.pk}/").json()
    assert detail["assets"] == {"documents": [], "images": [], "procedure": None}


# --- UI -----------------------------------------------------------------------


def test_documentation_page_renders(editor_client, model):
    _procedure(model)
    response = editor_client.get(f"/models/{model.pk}/documentation/")
    assert response.status_code == 200
    assert "Oživení APZ V2".encode() in response.content


def test_upload_document_and_reject_non_pdf(editor_client, model):
    url = f"/models/{model.pk}/documents/add/"
    ok = editor_client.post(url, {"title": "Manual", "file": SimpleUploadedFile("m.pdf", PDF)})
    assert ok.status_code == 302
    doc = model.documents.get()
    assert doc.uploaded_by.username == "ed"
    assert doc.file.name == f"models/{model.key}/m.pdf"

    bad = editor_client.post(url, {"title": "Nope", "file": SimpleUploadedFile("m.txt", b"x")}, follow=True)
    assert model.documents.count() == 1
    assert b"file:" in bad.content

    served = editor_client.get(f"/models/{model.pk}/documents/{doc.pk}/file/")
    assert served.status_code == 200 and b"".join(served.streaming_content) == PDF

    editor_client.post(f"/models/{model.pk}/documents/{doc.pk}/delete/")
    assert model.documents.count() == 0


def test_image_upload_primary_switch_and_delete(editor_client, model):
    add = f"/models/{model.pk}/images/add/"
    editor_client.post(add, {"image": SimpleUploadedFile("a.png", PNG), "caption": "A"})
    editor_client.post(add, {"image": SimpleUploadedFile("b.webp", PNG), "caption": "B"})
    a, b = model.images.order_by("created")
    assert a.is_primary and not b.is_primary

    editor_client.post(f"/models/{model.pk}/images/{b.pk}/primary/")
    a.refresh_from_db()
    b.refresh_from_db()
    assert b.is_primary and not a.is_primary

    editor_client.post(f"/models/{model.pk}/images/{b.pk}/delete/")
    a.refresh_from_db()
    assert model.images.count() == 1 and a.is_primary


def test_procedure_edit_creates_then_bumps_version(editor_client, model):
    url = f"/models/{model.pk}/procedure/edit/"
    assert editor_client.get(url).status_code == 200
    data = {"title": "Oživení", "body": "## 1. Krok", "duration_min": "5", "tools": "čtečka QR, Bridge",
            "requires_input": ["wmbus_id", "wmbus_key"]}
    assert editor_client.post(url, data).status_code == 302
    proc = model.procedure
    assert proc.version == 1
    assert proc.front_matter == {"duration_min": 5, "tools": ["čtečka QR", "Bridge"], "requires_input": ["wmbus_id", "wmbus_key"]}
    assert proc.updated_by.username == "ed"

    editor_client.post(url, data)  # unchanged: no bump
    proc.refresh_from_db()
    assert proc.version == 1

    editor_client.post(url, {**data, "body": "## 1. Krok\n## 2. Další"})
    proc.refresh_from_db()
    assert proc.version == 2

    editor_client.post(f"/models/{model.pk}/procedure/delete/")
    assert not ModelProcedure.objects.filter(vendor_model=model).exists()
    assert editor_client.post(f"/models/{model.pk}/procedure/delete/").status_code == 404


def test_viewer_cannot_mutate_assets(model):
    viewer = User.objects.create_user(username="v", password="x", role=User.Role.VIEWER)
    client = APIClient()
    client.force_login(viewer)
    response = client.post(f"/models/{model.pk}/documents/add/", {"title": "M", "file": SimpleUploadedFile("m.pdf", PDF)})
    assert response.status_code == 403
    assert model.documents.count() == 0
