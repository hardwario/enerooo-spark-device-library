# Generated manually

import django.db.models.deletion
import django.utils.timezone
import model_utils.fields
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("library", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceHistory",
            fields=[
                (
                    "created",
                    model_utils.fields.AutoCreatedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="created",
                    ),
                ),
                (
                    "modified",
                    model_utils.fields.AutoLastModifiedField(
                        default=django.utils.timezone.now,
                        editable=False,
                        verbose_name="modified",
                    ),
                ),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("device_label", models.CharField(max_length=255)),
                ("version", models.PositiveIntegerField()),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("created", "Created"),
                            ("updated", "Updated"),
                            ("deleted", "Deleted"),
                        ],
                        max_length=10,
                    ),
                ),
                ("snapshot", models.JSONField(default=dict)),
                ("changes", models.JSONField(default=dict)),
                (
                    "device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="history",
                        to="library.vendormodel",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="device_history",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created"],
                "unique_together": {("device", "version")},
                "indexes": [
                    models.Index(
                        fields=["device", "-created"],
                        name="library_dev_device__idx",
                    ),
                ],
            },
        ),
    ]
