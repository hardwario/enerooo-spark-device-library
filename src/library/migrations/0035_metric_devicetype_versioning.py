"""Versioning parity for L1 Metric + L2 DeviceType.

Adds the same per-row history + per-LibraryVersion manifest tables
that ``VendorModel`` already had via ``DeviceHistory`` /
``LibraryVersionDevice``. Without this, published library versions
would inherit the *current* state of metrics and device types — an
operator editing a metric's bounds would retroactively rewrite every
historical version.

Backfill: every existing Metric and DeviceType row gets a CREATED v1
history entry so the post-migration state is consistent with what a
fresh installation would have (each row's first save = v1). Skipped
when a history entry already exists (idempotent).
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
from django.conf import settings
from django.db import migrations, models


def backfill_v1_history(apps, schema_editor):
    """Create a v1 ``MetricHistory`` / ``DeviceTypeHistory`` entry for
    every existing row so ``LibraryContentViewSet`` can resolve them
    via the snapshot path going forward.

    Uses the historical model state via ``apps.get_model`` so the
    snapshot logic stays in lockstep with whatever the schema looked
    like at migration time — not whatever ``snapshot_metric`` does
    today.
    """
    Metric = apps.get_model("library", "Metric")
    DeviceType = apps.get_model("library", "DeviceType")
    MetricHistory = apps.get_model("library", "MetricHistory")
    DeviceTypeHistory = apps.get_model("library", "DeviceTypeHistory")

    for m in Metric.objects.all():
        if MetricHistory.objects.filter(metric=m).exists():
            continue
        snapshot = {
            "key": m.key,
            "label": m.label,
            "unit": m.unit or "",
            "data_type": m.data_type,
            "description": m.description or "",
            "min_value": str(m.min_value) if m.min_value is not None else None,
            "max_value": str(m.max_value) if m.max_value is not None else None,
            "monotonic": bool(m.monotonic),
            "aggregation": m.aggregation or "avg",
            "kind": m.kind or "measurement",
        }
        MetricHistory.objects.create(
            metric=m,
            metric_key=m.key,
            version=1,
            action="created",
            snapshot=snapshot,
            changes={},
        )

    for dt in DeviceType.objects.all():
        if DeviceTypeHistory.objects.filter(device_type=dt).exists():
            continue
        snapshot = {
            "code": dt.code,
            "key": str(dt.key) if dt.key else None,
            "label": dt.label,
            "description": dt.description or "",
            "icon": dt.icon or "",
            "metrics": list(dt.metrics or []),
        }
        DeviceTypeHistory.objects.create(
            device_type=dt,
            device_type_code=dt.code,
            version=1,
            action="created",
            snapshot=snapshot,
            changes={},
        )


def clear_backfill_history(apps, schema_editor):
    """Reverse the backfill — used by ``migrate library 0034``."""
    MetricHistory = apps.get_model("library", "MetricHistory")
    DeviceTypeHistory = apps.get_model("library", "DeviceTypeHistory")
    MetricHistory.objects.filter(version=1, action="created").delete()
    DeviceTypeHistory.objects.filter(version=1, action="created").delete()


class Migration(migrations.Migration):

    dependencies = [
        ('library', '0034_drop_controlconfig_capabilities'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='LibraryVersionDeviceType',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('device_type_version', models.PositiveIntegerField(default=1)),
                ('device_type_code', models.CharField(default='', max_length=64)),
                ('change_type', models.CharField(choices=[('added', 'Added'), ('modified', 'Modified'), ('removed', 'Removed'), ('unchanged', 'Unchanged')], max_length=20)),
                ('device_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='version_changes', to='library.devicetype')),
                ('library_version', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_type_changes', to='library.libraryversion')),
            ],
            options={
                'ordering': ['change_type', 'device_type_code'],
            },
        ),
        migrations.CreateModel(
            name='LibraryVersionMetric',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('metric_version', models.PositiveIntegerField(default=1)),
                ('metric_key', models.CharField(default='', max_length=128)),
                ('change_type', models.CharField(choices=[('added', 'Added'), ('modified', 'Modified'), ('removed', 'Removed'), ('unchanged', 'Unchanged')], max_length=20)),
                ('library_version', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='metric_changes', to='library.libraryversion')),
                ('metric', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='version_changes', to='library.metric')),
            ],
            options={
                'ordering': ['change_type', 'metric_key'],
            },
        ),
        migrations.CreateModel(
            name='DeviceTypeHistory',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('device_type_code', models.CharField(default='', max_length=64)),
                ('version', models.PositiveIntegerField()),
                ('action', models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('deleted', 'Deleted')], max_length=10)),
                ('snapshot', models.JSONField(default=dict)),
                ('changes', models.JSONField(default=dict)),
                ('device_type', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='history', to='library.devicetype')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='device_type_history', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created'],
                'indexes': [models.Index(fields=['device_type', '-created'], name='library_dev_device__610774_idx')],
                'unique_together': {('device_type', 'version')},
            },
        ),
        migrations.CreateModel(
            name='MetricHistory',
            fields=[
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('metric_key', models.CharField(default='', max_length=128)),
                ('version', models.PositiveIntegerField()),
                ('action', models.CharField(choices=[('created', 'Created'), ('updated', 'Updated'), ('deleted', 'Deleted')], max_length=10)),
                ('snapshot', models.JSONField(default=dict)),
                ('changes', models.JSONField(default=dict)),
                ('metric', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='history', to='library.metric')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='metric_history', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created'],
                'indexes': [models.Index(fields=['metric', '-created'], name='library_met_metric__5a889c_idx')],
                'unique_together': {('metric', 'version')},
            },
        ),
        migrations.RunPython(backfill_v1_history, clear_backfill_history),
    ]
