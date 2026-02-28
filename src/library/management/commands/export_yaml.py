"""Management command to export device definitions to YAML files."""

from django.core.management.base import BaseCommand

from library.exporters import export_to_yaml


class Command(BaseCommand):
    help = "Export device definitions from the database to YAML files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            required=True,
            help="Output directory for YAML files",
        )

    def handle(self, *args, **options):
        self.stdout.write(f"Exporting to {options['output_dir']}...")

        stats = export_to_yaml(output_dir=options["output_dir"])

        self.stdout.write(self.style.SUCCESS(
            f"Export complete: "
            f"{stats['vendors_exported']} vendors, "
            f"{stats['devices_exported']} devices exported"
        ))
