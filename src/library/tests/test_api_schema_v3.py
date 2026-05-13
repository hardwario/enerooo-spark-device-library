"""Tests for the REST API surface."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from library.models import Vendor, VendorModel

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def staff_client(db):
    user = User.objects.create_user(
        username="staff", password="x", is_staff=True, is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.fixture
def water_vendor_model(db, water_meter_type):
    vendor = Vendor.objects.create(name="Acme Water", slug="acme-water")
    return VendorModel.objects.create(
        vendor=vendor,
        model_number="W-100",
        name="Acme Water 100",
        device_type="water_meter",
        device_type_fk=water_meter_type,
        technology=VendorModel.Technology.WMBUS,
    )


class TestManifestEndpoint:
    def test_schema_version_is_4(self, staff_client):
        response = staff_client.get("/api/v1/manifest/")
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == 4

    def test_device_type_count_present(self, staff_client, water_meter_type):
        response = staff_client.get("/api/v1/manifest/")
        body = response.json()
        assert body["device_type_count"] >= 1


class TestSyncEndpoint:
    def test_includes_device_types_section(self, staff_client, water_vendor_model):
        response = staff_client.get("/api/v1/sync/")
        assert response.status_code == 200
        body = response.json()
        assert "device_types" in body
        codes = {dt["code"] for dt in body["device_types"]}
        assert "water_meter" in codes

    def test_each_device_type_carries_metadata(self, staff_client, water_meter_type):
        response = staff_client.get("/api/v1/sync/")
        body = response.json()
        water = next(dt for dt in body["device_types"] if dt["code"] == "water_meter")
        assert water["icon"] == "droplet"
        # L2 semantic profile lives under ``metrics``
        assert "metrics" in water
        # Legacy fields are gone
        assert "default_field_mappings" not in water
        assert "default_offline_window_seconds" not in water
        assert "primary_field_names" not in water

    def test_vendor_model_carries_per_meter_offline_window(self, staff_client, water_vendor_model):
        response = staff_client.get("/api/v1/sync/")
        body = response.json()
        vendor_block = next(v for v in body["vendors"] if v["name"] == "Acme Water")
        model = vendor_block["models"][0]
        # Backfilled from the seeded DeviceType default during migration 0022
        assert model["offline_window_seconds"] is None or isinstance(
            model["offline_window_seconds"], int,
        )
        # The merged effective list is exposed for clients that want a
        # one-shot read; processor_config carries the override/extra split.
        assert "effective_field_mappings" in model
        assert "processor_config" in model

    def test_vendor_model_carries_device_type_key(self, staff_client, water_vendor_model):
        response = staff_client.get("/api/v1/sync/")
        body = response.json()
        vendor_block = next(
            v for v in body["vendors"] if v["name"] == "Acme Water"
        )
        model = vendor_block["models"][0]
        # Both the legacy enum string and the FK pointer are exposed — older
        # clients read ``device_type``; newer ones prefer ``device_type_key``.
        assert model["device_type"] == "water_meter"
        assert model["device_type_key"] is not None

    def test_sync_carries_l1_metric_catalogue_with_bounds(self, staff_client):
        """Spark and other consumers pull L1 metric bounds from the sync
        endpoint — same payload as the YAML manifest, so an instance can
        replace its hardcoded METRIC_LIMITS / NON_NEGATIVE_METRICS tables."""
        response = staff_client.get("/api/v1/sync/")
        body = response.json()
        assert "metrics" in body
        by_key = {m["key"]: m for m in body["metrics"]}
        assert "heat:total_energy" in by_key
        # Seeded cumulative counter: monotonic + non-negative floor + delta agg
        heat = by_key["heat:total_energy"]
        assert heat["monotonic"] is True
        assert heat["min_value"] is not None
        assert heat["aggregation"] == "delta"
        # Instantaneous quantity: bounded, not monotonic, default avg agg
        temp = by_key["env:temperature"]
        assert temp["monotonic"] is False
        assert temp["min_value"] is not None
        assert temp["max_value"] is not None
        assert temp["aggregation"] == "avg"
        # Stateful telemetry: last-value aggregation
        assert by_key["device:battery"]["aggregation"] == "last"

    def test_effective_field_mappings_carry_bounds_per_entry(
        self, staff_client, water_vendor_model
    ):
        """Spark reads ranges per-entry from ``effective_field_mappings``
        without a separate L1 lookup."""
        from library.models import ProcessorConfig

        water_vendor_model.device_type_fk.metrics = [
            {"metric": "water:total_volume", "tier": "primary"},
            {"metric": "water:flow_rate", "tier": "primary"},
        ]
        water_vendor_model.device_type_fk.save(update_fields=["metrics"])
        ProcessorConfig.objects.create(
            device_type=water_vendor_model,
            field_mappings=[
                {"source": "vol_m3", "target": "water:total_volume"},
                {"source": "q", "target": "water:flow_rate"},
            ],
        )
        response = staff_client.get("/api/v1/sync/")
        body = response.json()
        vendor_block = next(v for v in body["vendors"] if v["name"] == "Acme Water")
        model = vendor_block["models"][0]
        entries = {e["target"]: e for e in model["effective_field_mappings"]}
        # water:total_volume is monotonic + non-negative + delta aggregation
        vol = entries["water:total_volume"]
        assert vol["monotonic"] is True
        assert vol["min_value"] is not None
        assert vol["aggregation"] == "delta"
        # water:flow_rate is not monotonic — flag omitted, bounds present,
        # aggregation defaults to avg so it's also omitted (compact payload).
        flow = entries["water:flow_rate"]
        assert "monotonic" not in flow
        assert flow["min_value"] is not None
        assert flow["max_value"] is not None
        assert "aggregation" not in flow


class TestDeviceTypesEndpoint:
    def test_lists_existing_types(self, staff_client, water_meter_type, heat_meter_type, gas_meter_type):
        response = staff_client.get("/api/v1/device_types/")
        assert response.status_code == 200
        body = response.json()
        # DRF default pagination wraps in a dict; ReadOnlyModelViewSet might
        # also return a bare list when pagination disabled. Handle both.
        results = body if isinstance(body, list) else body.get("results", [])
        codes = {dt["code"] for dt in results}
        assert {"water_meter", "heat_meter", "gas_meter"}.issubset(codes)

    def test_lookup_by_code(self, staff_client, water_meter_type):
        response = staff_client.get("/api/v1/device_types/water_meter/")
        assert response.status_code == 200
        body = response.json()
        assert body["code"] == "water_meter"
        assert body["icon"] == "droplet"
        # L2 semantic profile (metric/tier list) is on the type
        assert "metrics" in body
        assert "default_field_mappings" not in body


class TestLibraryContentEndpoint:
    """``/api/v1/library/content/<version>/`` is service-token authenticated;
    we hit it via the underlying viewset to keep the test focused on the
    payload shape without re-implementing the HMAC check."""

    def test_includes_device_types_for_a_published_version(self, db, rf, water_meter_type):
        from library.api.viewsets import LibraryContentViewSet
        from library.models import LibraryVersion

        lv = LibraryVersion.objects.create(version=1, schema_version=4, is_current=True)
        view = LibraryContentViewSet()
        view.request = rf.get(f"/api/v1/library/content/{lv.version}/")
        response = view.retrieve(view.request, pk=str(lv.version))

        assert response.status_code == 200
        assert response.data["schema_version"] == 4
        assert "device_types" in response.data
        assert any(dt["code"] == "water_meter" for dt in response.data["device_types"])
