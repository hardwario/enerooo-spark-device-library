"""Tests for the unpublished-changes detector and banner.

Covers four states for each entity type (VendorModel / Metric /
DeviceType): no LibraryVersion yet, after edit, after publish, and
after a new entity is created post-publish. Also asserts the
context processor exposes the summary and the base template
renders the banner when the total is non-zero.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory
from django.urls import reverse

from library.context_processors import unpublished_changes as ctx_unpublished
from library.history import (
    record_device_type_history,
    record_history,
    record_metric_history,
    snapshot_device,
    snapshot_device_type,
    snapshot_metric,
)
from library.models import (
    DeviceHistory,
    DeviceType,
    DeviceTypeHistory,
    LibraryVersion,
    Metric,
    MetricHistory,
    Vendor,
    VendorModel,
)
from library.unpublished import unpublished_changes_summary

pytestmark = pytest.mark.django_db
User = get_user_model()


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


@pytest.fixture
def admin_user(db):
    return User.objects.create_user(
        username="banner-admin",
        password="x",
        is_staff=True,
        is_superuser=True,
        role="admin",
    )


@pytest.fixture
def admin_session_client(admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


def _make_vendor_model(slug: str = "acme") -> VendorModel:
    vendor, _ = Vendor.objects.get_or_create(name=f"Vendor-{slug}", slug=slug)
    vm = VendorModel.objects.create(
        vendor=vendor,
        model_number=f"M-{slug}",
        name=f"Model {slug}",
        device_type="water_meter",
        technology=VendorModel.Technology.WMBUS,
    )
    record_history(vm, DeviceHistory.Action.CREATED, user=None)
    return vm


def _publish(client) -> LibraryVersion:
    """Drive the real publish flow rather than constructing manifest
    rows by hand — keeps the test honest about the production path."""
    response = client.post(reverse("library:version-create"))
    assert response.status_code in (200, 302), response.status_code
    return LibraryVersion.objects.get(is_current=True)


# -----------------------------------------------------------------------------
# Empty / pristine state
# -----------------------------------------------------------------------------


class TestPristine:
    def test_no_library_version_yet_treats_existing_entities_as_unpublished(self):
        # The migration seeds Metric + DeviceType rows; without a
        # publish ever, all of them count as unpublished additions.
        summary = unpublished_changes_summary()
        assert summary.current_version is None
        assert summary.next_version == 1
        assert summary.total > 0
        assert all(e.change_type == "added" for e in summary.metrics)
        assert all(e.change_type == "added" for e in summary.device_types)

    def test_after_publish_total_is_zero(self, admin_session_client):
        _publish(admin_session_client)
        summary = unpublished_changes_summary()
        assert summary.total == 0
        assert summary.current_version == 1
        assert summary.next_version == 2


# -----------------------------------------------------------------------------
# Modified detection — VendorModel
# -----------------------------------------------------------------------------


class TestVendorModelChanges:
    def test_edited_model_after_publish_shows_as_modified(self, admin_session_client):
        vm = _make_vendor_model("modtest")
        _publish(admin_session_client)
        assert unpublished_changes_summary().total == 0

        prev = snapshot_device(vm)
        vm.description = "edited"
        vm.save()
        record_history(vm, DeviceHistory.Action.UPDATED, user=None, previous_snapshot=prev)

        summary = unpublished_changes_summary()
        modified = [e for e in summary.models if e.change_type == "modified"]
        assert len(modified) == 1
        assert modified[0].pk == str(vm.pk)

    def test_new_model_after_publish_shows_as_added(self, admin_session_client):
        _publish(admin_session_client)
        vm = _make_vendor_model("addtest")
        summary = unpublished_changes_summary()
        added = [e for e in summary.models if e.change_type == "added" and e.pk == str(vm.pk)]
        assert len(added) == 1

    def test_deleted_model_after_publish_shows_as_removed(self, admin_session_client):
        vm = _make_vendor_model("deltest")
        label = str(vm)
        _publish(admin_session_client)
        vm.delete()
        summary = unpublished_changes_summary()
        removed = [e for e in summary.models if e.change_type == "removed"]
        assert len(removed) == 1
        assert removed[0].label == label
        assert removed[0].detail_url_name is None


# -----------------------------------------------------------------------------
# Modified detection — Metric + DeviceType
# -----------------------------------------------------------------------------


class TestMetricChanges:
    def test_edited_metric_shows_as_modified(self, admin_session_client):
        m = Metric.objects.create(key="x:banner_test", label="V1", data_type="decimal")
        record_metric_history(m, MetricHistory.Action.CREATED, user=None)
        _publish(admin_session_client)
        assert unpublished_changes_summary().total == 0

        prev = snapshot_metric(m)
        m.label = "V2"
        m.save()
        record_metric_history(m, MetricHistory.Action.UPDATED, user=None, previous_snapshot=prev)

        summary = unpublished_changes_summary()
        match = [e for e in summary.metrics if e.pk == str(m.pk)]
        assert len(match) == 1
        assert match[0].change_type == "modified"
        assert match[0].label == "x:banner_test"


class TestDeviceTypeChanges:
    def test_edited_device_type_shows_as_modified(self, admin_session_client):
        dt = DeviceType.objects.create(code="x_banner_type", label="X Banner")
        record_device_type_history(dt, DeviceTypeHistory.Action.CREATED, user=None)
        _publish(admin_session_client)
        assert unpublished_changes_summary().total == 0

        prev = snapshot_device_type(dt)
        dt.label = "X Banner Updated"
        dt.save()
        record_device_type_history(
            dt,
            DeviceTypeHistory.Action.UPDATED,
            user=None,
            previous_snapshot=prev,
        )

        summary = unpublished_changes_summary()
        match = [e for e in summary.device_types if e.pk == str(dt.pk)]
        assert len(match) == 1
        assert match[0].change_type == "modified"


# -----------------------------------------------------------------------------
# Context processor + banner rendering
# -----------------------------------------------------------------------------


class TestContextProcessor:
    def test_anonymous_request_returns_empty(self):
        request = RequestFactory().get("/")
        request.user = type("Anon", (), {"is_authenticated": False})()
        assert ctx_unpublished(request) == {}

    def test_authenticated_request_includes_summary(self, admin_user):
        request = RequestFactory().get("/")
        request.user = admin_user
        ctx = ctx_unpublished(request)
        assert "unpublished_changes" in ctx
        assert "total" in ctx["unpublished_changes"]


class TestBannerRendering:
    def test_banner_renders_when_total_nonzero(self, admin_session_client):
        response = admin_session_client.get(reverse("library:dashboard"))
        assert response.status_code == 200
        body = response.content.decode()
        assert "unpublished change" in body
        assert "Publish v1" in body

    def test_banner_hidden_after_publish(self, admin_session_client):
        _publish(admin_session_client)
        response = admin_session_client.get(reverse("library:dashboard"))
        body = response.content.decode()
        assert "unpublished change" not in body
