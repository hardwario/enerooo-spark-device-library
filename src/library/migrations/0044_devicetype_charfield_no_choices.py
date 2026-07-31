from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("library", "0043_resnapshot_lorawan_ttn_profile"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendormodel",
            name="device_type",
            field=models.CharField(blank=True, default="", max_length=30),
        ),
    ]
