"""Tests for the instance-facing GatewayAssignment API (library-first claim):
Spark instances retrieve a single gateway's assignment during box
self-registration and list their own assignments during library sync."""

import time

import pytest
from rest_framework.test import APIClient

from library.models import GatewayAssignment

TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def _service_token(settings):
    settings.SERVICE_TOKEN = TOKEN


@pytest.fixture
def api():
    client = APIClient()
    client.credentials(
        HTTP_X_SERVICE_TOKEN=TOKEN,
        HTTP_X_TIMESTAMP=str(int(time.time())),
    )
    return client


@pytest.fixture
def assignments(db):
    a = GatewayAssignment.objects.create(
        serial_number="ER10C-AAAAA-01",
        spark_url="https://alpha.spark.enerooo.cloud",
        is_assigned=True,
    )
    b = GatewayAssignment.objects.create(
        serial_number="ER10C-BBBBB-02",
        spark_url="https://beta.spark.enerooo.cloud",
        is_assigned=True,
    )
    return a, b


class TestRetrieve:
    def test_retrieve_by_serial(self, api, assignments):
        resp = api.get("/api/v1/assignments/ER10C-AAAAA-01/")
        assert resp.status_code == 200
        assert resp.data["spark_url"] == "https://alpha.spark.enerooo.cloud"
        assert resp.data["is_assigned"] is True

    def test_unknown_serial_404(self, api, db):
        resp = api.get("/api/v1/assignments/ER10C-NOPE-99/")
        assert resp.status_code == 404

    def test_requires_service_token(self, assignments):
        resp = APIClient().get("/api/v1/assignments/ER10C-AAAAA-01/")
        assert resp.status_code in (401, 403)


class TestListFilter:
    def test_spark_url_filter_scopes_to_one_instance(self, api, assignments):
        resp = api.get(
            "/api/v1/assignments/",
            {"spark_url": "https://alpha.spark.enerooo.cloud"},
        )
        assert resp.status_code == 200
        serials = [r["serial_number"] for r in resp.data["results"]]
        assert serials == ["ER10C-AAAAA-01"]

    def test_trailing_slash_matches_too(self, api, assignments):
        resp = api.get(
            "/api/v1/assignments/",
            {"spark_url": "https://alpha.spark.enerooo.cloud/"},
        )
        serials = [r["serial_number"] for r in resp.data["results"]]
        assert serials == ["ER10C-AAAAA-01"]
