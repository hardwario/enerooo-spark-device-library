"""End-to-end render tests for the Change History UI on Metric and
DeviceType detail pages, plus the snapshot/diff drill-down views.

These verify URL routing, template rendering, and that the existing
``MetricHistory`` / ``DeviceTypeHistory`` rows from migration 0035 are
correctly surfaced — they pin the parity claim made in
``docs/architecture/versioning-parity.md``."""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from library.history import record_metric_history, snapshot_metric
from library.models import DeviceType, Metric, MetricHistory

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture
def admin_client(db):
    u = User.objects.create_user(
        username="hist-ui", password="x",
        is_staff=True, is_superuser=True, role="admin",
    )
    c = Client()
    c.force_login(u)
    return c


class TestMetricDetailHistoryTable:
    def test_renders_change_history_section(self, admin_client):
        m = Metric.objects.get(key="heat:total_energy")
        response = admin_client.get(f"/metrics/{m.pk}/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Change History" in body
        # v1 from migration 0035 backfill
        assert "v1" in body
        assert "Compare Selected" in body

    def test_history_table_shows_diff_after_edit(self, admin_client):
        # Create a fresh metric + edit it so the history table has 2 rows.
        m = Metric.objects.create(key="x:hist_test", label="V1", data_type="decimal")
        record_metric_history(m, MetricHistory.Action.CREATED, user=None)
        prev = snapshot_metric(m)
        m.label = "V2"
        m.save()
        record_metric_history(
            m, MetricHistory.Action.UPDATED, user=None, previous_snapshot=prev,
        )

        response = admin_client.get(f"/metrics/{m.pk}/")
        body = response.content.decode()
        # Both versions visible
        assert "v1" in body
        assert "v2" in body
        # Diff line shows the label change inline
        assert "V1" in body
        assert "V2" in body


class TestMetricHistorySnapshotView:
    def test_snapshot_view_renders_v1(self, admin_client):
        m = Metric.objects.get(key="heat:total_energy")
        response = admin_client.get(f"/metrics/{m.pk}/history/1/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Snapshot fields" in body
        # Confirm the snapshot carries kind + aggregation (v5 fields)
        assert "delta" in body  # aggregation
        assert "monotonic" in body.lower()

    def test_snapshot_view_404_on_missing_version(self, admin_client):
        m = Metric.objects.get(key="heat:total_energy")
        response = admin_client.get(f"/metrics/{m.pk}/history/9999/")
        assert response.status_code == 404


class TestMetricHistoryDiffView:
    def test_diff_between_two_versions(self, admin_client):
        m = Metric.objects.create(key="x:diff_test", label="Original", data_type="decimal")
        record_metric_history(m, MetricHistory.Action.CREATED, user=None)
        prev = snapshot_metric(m)
        m.label = "Renamed"
        m.save()
        record_metric_history(
            m, MetricHistory.Action.UPDATED, user=None, previous_snapshot=prev,
        )

        response = admin_client.get(f"/metrics/{m.pk}/history/diff/?from=1&to=2")
        assert response.status_code == 200
        body = response.content.decode()
        # The diff table renders the field, old value, new value
        assert "label" in body
        assert "Original" in body
        assert "Renamed" in body


class TestDeviceTypeDetailHistoryTable:
    def test_renders_change_history_section(self, admin_client):
        dt = DeviceType.objects.first()
        assert dt is not None
        response = admin_client.get(f"/device-types/{dt.pk}/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Change History" in body
        assert "v1" in body


class TestDeviceTypeHistorySnapshotView:
    def test_snapshot_view_renders_v1(self, admin_client):
        dt = DeviceType.objects.first()
        response = admin_client.get(f"/device-types/{dt.pk}/history/1/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Snapshot fields" in body
        assert "L2 metrics profile" in body
