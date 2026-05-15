"""Versioning parity for L1 Metric + L2 DeviceType.

These tests verify the schema-v5 versioning extension: every published
LibraryVersion can faithfully reproduce the catalogue (L1) and the
per-type profiles (L2) at that point in time. The classes mirror the
existing DeviceHistory / LibraryVersionDevice flow row-for-row.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from rest_framework.test import APIClient

from library.api.viewsets import LibraryContentViewSet
from library.history import (
    record_device_type_history,
    record_metric_history,
    snapshot_device_type,
    snapshot_metric,
)
from library.models import (
    DeviceType,
    DeviceTypeHistory,
    LibraryVersion,
    LibraryVersionDeviceType,
    LibraryVersionMetric,
    Metric,
    MetricHistory,
)

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def admin_client(db):
    user = User.objects.create_user(
        username="admin-ver", password="x", is_staff=True, is_superuser=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return client


# -----------------------------------------------------------------------------
# Migration backfill — every existing row should have a v1 history entry
# -----------------------------------------------------------------------------


class TestBackfill:
    def test_every_metric_has_v1_history(self):
        for m in Metric.objects.all():
            assert m.history.filter(version=1).exists(), (
                f"Metric {m.key} missing v1 history entry post-backfill"
            )

    def test_every_device_type_has_v1_history(self):
        for dt in DeviceType.objects.all():
            assert dt.history.filter(version=1).exists(), (
                f"DeviceType {dt.code} missing v1 history entry post-backfill"
            )

    def test_v1_snapshot_carries_kind_and_bounds(self):
        # Spot-check: heat:total_energy is a seeded cumulative counter
        # → v1 snapshot should preserve monotonic + delta + measurement.
        m = Metric.objects.get(key="heat:total_energy")
        snap = m.history.get(version=1).snapshot
        assert snap["key"] == "heat:total_energy"
        assert snap["monotonic"] is True
        assert snap["aggregation"] == "delta"
        assert snap["kind"] == "measurement"


# -----------------------------------------------------------------------------
# record_metric_history / record_device_type_history
# -----------------------------------------------------------------------------


class TestRecordHistory:
    def test_record_metric_history_creates_versioned_snapshot(self):
        m = Metric.objects.create(key="x:test1", label="Test1", data_type="decimal")
        record_metric_history(m, MetricHistory.Action.CREATED, user=None)
        h = m.history.get(version=1)
        assert h.action == "created"
        assert h.snapshot["label"] == "Test1"

    def test_subsequent_records_bump_version(self):
        m = Metric.objects.create(key="x:test2", label="V1", data_type="decimal")
        record_metric_history(m, MetricHistory.Action.CREATED, user=None)
        prev = snapshot_metric(m)
        m.label = "V2"
        m.save()
        record_metric_history(
            m, MetricHistory.Action.UPDATED, user=None, previous_snapshot=prev,
        )
        v2 = m.history.get(version=2)
        assert v2.action == "updated"
        assert v2.changes["label"]["new"] == "V2"
        assert v2.snapshot["label"] == "V2"

    def test_device_type_history_records_metrics_list_change(self):
        dt = DeviceType.objects.create(code="x_test_type", label="X Test")
        record_device_type_history(dt, DeviceTypeHistory.Action.CREATED, user=None)
        prev = snapshot_device_type(dt)
        dt.metrics = [{"metric": "heat:total_energy", "tier": "primary"}]
        dt.save()
        record_device_type_history(
            dt, DeviceTypeHistory.Action.UPDATED, user=None, previous_snapshot=prev,
        )
        v2 = dt.history.get(version=2)
        assert v2.changes["metrics"]["new"] == [
            {"metric": "heat:total_energy", "tier": "primary"},
        ]


# -----------------------------------------------------------------------------
# Publish flow — VersionCreateView snapshots Metric + DeviceType
# -----------------------------------------------------------------------------


@pytest.fixture
def admin_session_client(db):
    """Logged-in session client with admin role — needed for views
    behind ``RoleRequiredMixin(required_role=ADMIN)``."""
    from django.test import Client

    u = User.objects.create_user(
        username="admin-sess",
        password="x",
        is_staff=True,
        is_superuser=True,
        role="admin",
    )
    client = Client()
    client.force_login(u)
    return client


class TestPublishFlow:
    """``VersionCreateView`` should populate ``metric_changes`` and
    ``device_type_changes`` on the new LibraryVersion, mirroring the
    existing ``device_changes`` behaviour."""

    def _publish(self, client):
        return client.post("/versions/create/")

    def test_first_publish_marks_existing_metrics_as_added(self, admin_session_client):
        response = self._publish(admin_session_client)
        assert response.status_code in (302, 303), (
            f"Publish failed: {response.status_code} — body: {response.content[:200]!r}"
        )

        lv = LibraryVersion.objects.order_by("-version").first()
        assert lv is not None
        # Every existing metric should be ADDED on the first publish.
        added = lv.metric_changes.filter(
            change_type=LibraryVersionMetric.ChangeType.ADDED,
        ).count()
        assert added == Metric.objects.count()
        # Same for device types.
        added_dt = lv.device_type_changes.filter(
            change_type=LibraryVersionDeviceType.ChangeType.ADDED,
        ).count()
        assert added_dt == DeviceType.objects.count()

    def test_modified_metric_bumps_change_type(self, admin_session_client):
        """Publish v1, mutate a metric, publish v2 — the second
        version's manifest should mark that metric as MODIFIED."""
        # Publish v1
        self._publish(admin_session_client)

        # Mutate a metric
        m = Metric.objects.get(key="env:temperature")
        prev = snapshot_metric(m)
        m.label = "Temperature (changed)"
        m.save()
        record_metric_history(
            m, MetricHistory.Action.UPDATED, user=None, previous_snapshot=prev,
        )

        # Publish v2
        self._publish(admin_session_client)

        v2 = LibraryVersion.objects.order_by("-version").first()
        entry = v2.metric_changes.get(metric=m)
        assert entry.change_type == LibraryVersionMetric.ChangeType.MODIFIED
        assert entry.metric_version == 2  # v2 of MetricHistory

    def test_unmodified_metric_marked_unchanged_on_repeat_publish(self, admin_session_client):
        """Metrics that didn't move between publishes should be UNCHANGED,
        not re-marked ADDED. Same invariant as VendorModel."""
        self._publish(admin_session_client)
        self._publish(admin_session_client)

        v2 = LibraryVersion.objects.order_by("-version").first()
        m = Metric.objects.get(key="env:temperature")
        entry = v2.metric_changes.get(metric=m)
        assert entry.change_type == LibraryVersionMetric.ChangeType.UNCHANGED


# -----------------------------------------------------------------------------
# Content endpoint — serves snapshots, not current state
# -----------------------------------------------------------------------------


class TestContentEndpoint:
    """``/api/v1/library/content/<v>/`` resolves metrics + device_types
    from per-version manifest snapshots. After editing a metric and
    publishing a new version, the *old* version's content endpoint
    must still serve the *old* snapshot."""

    def test_old_version_serves_old_metric_snapshot(self, admin_session_client):
        # Publish v1 with current state
        admin_session_client.post("/versions/create/")
        v1 = LibraryVersion.objects.order_by("-version").first()

        # Mutate a metric: env:temperature label
        m = Metric.objects.get(key="env:temperature")
        original_label = m.label
        prev = snapshot_metric(m)
        m.label = "Temperature (V2 label)"
        m.save()
        record_metric_history(
            m, MetricHistory.Action.UPDATED, user=None, previous_snapshot=prev,
        )

        # Publish v2 with the new state
        admin_session_client.post("/versions/create/")
        v2 = LibraryVersion.objects.order_by("-version").first()
        assert v2.version == v1.version + 1

        # Pull content for v1 — should still see the OLD label
        rf = RequestFactory()
        view = LibraryContentViewSet()
        req = rf.get(f"/api/v1/library/content/{v1.version}/")
        view.request = req
        resp_v1 = view.retrieve(req, pk=str(v1.version))
        m_in_v1 = next(x for x in resp_v1.data["metrics"] if x["key"] == "env:temperature")
        assert m_in_v1["label"] == original_label, (
            "Old library version should serve the historical metric snapshot, "
            "not the current state of the row."
        )

        # Pull content for v2 — should see the NEW label
        req_v2 = rf.get(f"/api/v1/library/content/{v2.version}/")
        view.request = req_v2
        resp_v2 = view.retrieve(req_v2, pk=str(v2.version))
        m_in_v2 = next(x for x in resp_v2.data["metrics"] if x["key"] == "env:temperature")
        assert m_in_v2["label"] == "Temperature (V2 label)"

    def test_pre_0035_version_falls_back_to_current_state(self):
        """A LibraryVersion published before migration 0035 has no
        metric_changes / device_type_changes rows. The endpoint should
        not crash — it falls back to serving current state for L1+L2."""
        # Construct a synthetic LibraryVersion with no manifest entries
        # (simulates a pre-0035 publish). Don't go through VersionCreateView
        # because that would create manifest entries now.
        lv = LibraryVersion.objects.create(version=99999, is_current=False)

        rf = RequestFactory()
        view = LibraryContentViewSet()
        req = rf.get(f"/api/v1/library/content/{lv.version}/")
        view.request = req
        resp = view.retrieve(req, pk=str(lv.version))

        assert resp.status_code == 200
        # Should fall back to current Metric.objects.all()
        assert any(m["key"] == "heat:total_energy" for m in resp.data["metrics"])
        assert any(dt["code"] == "water_meter" for dt in resp.data["device_types"])
