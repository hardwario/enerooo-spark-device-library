from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("library", "0015_alter_wmbusconfig_shared_encryption_key"),
    ]

    operations = [
        migrations.AddField(
            model_name="wmbusconfig",
            name="wmbus_version",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Hex byte from telegram header, e.g. 1b",
                max_length=4,
            ),
        ),
    ]
