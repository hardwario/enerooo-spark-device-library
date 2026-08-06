from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0044_devicetype_charfield_no_choices"),
    ]

    operations = [
        migrations.AddField(
            model_name="gatewayassignment",
            name="name",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Friendly label for this gateway (e.g. ZAK0) — library-side only.",
                max_length=255,
            ),
        ),
    ]
