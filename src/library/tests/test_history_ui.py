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


class TestVersionDetailManifests:
    """``/versions/<pk>/`` should expose three manifests: Metric (L1),
    DeviceType (L2), and Model (L4). Each manifest links into the
    matching snapshot view. Pins the parity the user asked for —
    publishing tracks L1/L2/L4 alike."""

    def test_renders_all_three_manifests(self, admin_client):
        from library.models import LibraryVersion

        # Publish a version (admin client routes through real view).
        admin_client.post("/versions/create/")
        lv = LibraryVersion.objects.order_by("-version").first()
        assert lv is not None

        response = admin_client.get(f"/versions/{lv.pk}/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "Metric Manifest" in body
        assert "Device Type Manifest" in body
        assert "Model Manifest" in body
        # Anchor IDs the in-page Details counters link to
        assert 'id="metric-manifest"' in body
        assert 'id="devicetype-manifest"' in body
        assert 'id="model-manifest"' in body

    def test_metric_manifest_links_to_metric_snapshot(self, admin_client):
        from library.models import LibraryVersion

        admin_client.post("/versions/create/")
        lv = LibraryVersion.objects.order_by("-version").first()
        response = admin_client.get(f"/versions/{lv.pk}/")
        body = response.content.decode()
        # At least one metric snapshot link should be present
        assert "/metrics/" in body
        assert "/history/1/" in body  # backfilled v1 from migration 0035

    def test_pre_0035_version_shows_empty_state_messages(self, admin_client):
        """A LibraryVersion published before the 0035 migration (or
        otherwise without manifest entries) renders the empty-state
        copy instead of crashing."""
        from library.models import LibraryVersion

        # Synthetic pre-0035 version: no manifest entries on any of
        # the three change tables.
        lv = LibraryVersion.objects.create(version=99998, is_current=False)
        response = admin_client.get(f"/versions/{lv.pk}/")
        assert response.status_code == 200
        body = response.content.decode()
        assert "published before migration 0035" in body

    def test_unchanged_hidden_by_default_with_count_link(self, admin_client):
        """First publish marks every existing Metric/DeviceType as
        ADDED — second publish marks them all UNCHANGED. The second
        version's detail page should hide those unchanged rows by
        default and offer a 'show all' toggle."""
        from library.models import LibraryVersion

        # v1: everything ADDED
        admin_client.post("/versions/create/")
        # v2: no entity changes → everything UNCHANGED
        admin_client.post("/versions/create/")

        v2 = LibraryVersion.objects.order_by("-version").first()
        response = admin_client.get(f"/versions/{v2.pk}/")
        body = response.content.decode()

        # Toggle link exposes the hidden count
        assert "unchanged hidden — show all" in body
        # Empty-state message in each section (since all 88 metrics
        # are unchanged in v2, default view shows none of them).
        assert "every L1 entry is unchanged" in body

    def test_show_unchanged_toggle_reveals_all_rows(self, admin_client):
        from library.models import LibraryVersion, Metric

        admin_client.post("/versions/create/")
        admin_client.post("/versions/create/")

        v2 = LibraryVersion.objects.order_by("-version").first()
        # With the toggle on, an arbitrary unchanged metric key
        # (e.g. heat:total_energy from the seed catalogue) shows up.
        response = admin_client.get(f"/versions/{v2.pk}/?show_unchanged=1")
        body = response.content.decode()
        sample_key = Metric.objects.values_list("key", flat=True).first()
        assert sample_key in body
        # And the toggle now reads "Hide unchanged"
        assert "Hide unchanged" in body
