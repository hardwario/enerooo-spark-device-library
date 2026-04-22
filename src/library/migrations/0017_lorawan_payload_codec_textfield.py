"""Change LoRaWANConfig.payload_codec from JSONField to TextField and add codec_format."""

from django.db import migrations, models


def convert_json_to_text(apps, schema_editor):
    """Convert any existing JSONField payload_codec data to empty string.

    The old JSONField stored dicts (default {}). Since no real JS codecs
    were stored yet, we simply reset to empty string for the new TextField.
    """
    LoRaWANConfig = apps.get_model("library", "LoRaWANConfig")
    LoRaWANConfig.objects.all().update(payload_codec="")


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0016_wmbusconfig_wmbus_version"),
    ]

    operations = [
        # Step 1: Add codec_format field
        migrations.AddField(
            model_name="lorawanconfig",
            name="codec_format",
            field=models.CharField(
                blank=True,
                choices=[
                    ("ttn_v3", "TTN v3 (decodeUplink / encodeDownlink)"),
                    ("ttn_v2", "TTN v2 Legacy (Decoder / Encoder)"),
                    ("chirpstack", "ChirpStack v4"),
                ],
                default="ttn_v3",
                max_length=16,
            ),
        ),
        # Step 2: Convert existing JSON data to empty string before field type change
        migrations.RunPython(convert_json_to_text, migrations.RunPython.noop),
        # Step 3: Change payload_codec from JSONField to TextField
        migrations.AlterField(
            model_name="lorawanconfig",
            name="payload_codec",
            field=models.TextField(
                blank=True,
                default="",
                help_text="JavaScript source implementing decodeUplink/encodeDownlink (TTN v3/ChirpStack) or Decoder/Encoder (TTN v2).",
            ),
        ),
    ]
