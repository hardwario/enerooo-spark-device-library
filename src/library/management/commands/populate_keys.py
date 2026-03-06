"""Management command to populate missing key UUIDs on Vendor and VendorModel."""

import uuid

from django.core.management.base import BaseCommand

from library.models import Vendor, VendorModel


class Command(BaseCommand):
    help = "Set a random UUID key on Vendor and VendorModel records that don't have one."

    def handle(self, *args, **options):
        vendor_count = 0
        for vendor in Vendor.objects.filter(key__isnull=True):
            vendor.key = uuid.uuid4()
            vendor.save(update_fields=["key"])
            vendor_count += 1

        model_count = 0
        for model in VendorModel.objects.filter(key__isnull=True):
            model.key = uuid.uuid4()
            model.save(update_fields=["key"])
            model_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"Populated {vendor_count} vendor(s) and {model_count} model(s) with keys."
        ))
