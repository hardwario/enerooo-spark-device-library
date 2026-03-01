"""Management command to create an API key."""

from django.core.management.base import BaseCommand

from library.models import APIKey


class Command(BaseCommand):
    help = "Create an API key and print its credentials for use with sync scripts"

    def add_arguments(self, parser):
        parser.add_argument("name", help="Descriptive name for the API key")

    def handle(self, *args, **options):
        key = APIKey.objects.create(name=options["name"])

        self.stdout.write(self.style.SUCCESS(f"API key '{key.name}' created.\n"))
        self.stdout.write(f"LIBRARY_KEY_ID={key.id}")
        self.stdout.write(f"LIBRARY_KEY_SECRET={key.key}")
