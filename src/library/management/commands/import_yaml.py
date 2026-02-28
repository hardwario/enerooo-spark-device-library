"""Management command to import device definitions from YAML files."""

from django.core.management.base import BaseCommand

from library.importers import import_from_yaml


class Command(BaseCommand):
    help = "Import device definitions from YAML files into the database"

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            required=True,
            help="Path to the devices/ directory containing YAML files",
        )
        parser.add_argument(
            "--manifest",
            required=True,
            help="Path to manifest.yaml",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing vendors and devices before importing",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Importing from {options['path']}...")

        stats = import_from_yaml(
            devices_path=options["path"],
            manifest_path=options["manifest"],
            clear=options["clear"],
        )

        self.stdout.write(self.style.SUCCESS(
            f"Import complete: "
            f"{stats['vendors_created']} vendors created, "
            f"{stats['vendors_updated']} vendors updated, "
            f"{stats['devices_created']} devices created, "
            f"{stats['devices_updated']} devices updated"
        ))

        if stats["errors"]:
            self.stdout.write(self.style.WARNING(f"\n{len(stats['errors'])} errors:"))
            for error in stats["errors"]:
                self.stdout.write(self.style.ERROR(f"  - {error}"))
