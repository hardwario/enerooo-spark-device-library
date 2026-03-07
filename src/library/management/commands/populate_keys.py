"""Management command to populate missing key UUIDs on Vendor and VendorModel."""

import uuid

from django.core.management.base import BaseCommand

from library.history import record_history, snapshot_device
from library.models import DeviceHistory, Vendor, VendorModel


class Command(BaseCommand):
    help = "Set a random UUID key on Vendor and VendorModel records that don't have one."

    def handle(self, *args, **options):
        vendor_count = 0
        for vendor in Vendor.objects.filter(key__isnull=True):
            vendor.key = uuid.uuid4()
            vendor.save(update_fields=["key"])
            vendor_count += 1

        model_count = 0
        for model in VendorModel.objects.select_related(
            "vendor", "modbus_config", "lorawan_config",
            "wmbus_config", "control_config", "processor_config",
        ).filter(key__isnull=True):
            previous = snapshot_device(model)
            model.key = uuid.uuid4()
            model.save(update_fields=["key"])
            record_history(model, DeviceHistory.Action.UPDATED, user=None, previous_snapshot=previous)
            model_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Populated {vendor_count} vendor(s) and {model_count} model(s) with keys."
        ))
