"""Replace numeric latest/minimum versions with display-only string versions.

The update decision no longer uses version comparisons — it is driven purely
by `enabled` + `mode`. Old numeric values are dropped; the new fields start
blank (display-only, e.g. "2.4" / "3.89").
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("appupdate", "0001_initial"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="appupdateconfig",
            name="latest_version_gte_minimum_version",
        ),
        migrations.RemoveField(
            model_name="appupdateconfig",
            name="latest_version",
        ),
        migrations.RemoveField(
            model_name="appupdateconfig",
            name="minimum_version",
        ),
        migrations.AddField(
            model_name="appupdateconfig",
            name="current_version",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Version currently live on the Play Store (display only), "
                    "e.g. 2.4."
                ),
                max_length=32,
            ),
        ),
        migrations.AddField(
            model_name="appupdateconfig",
            name="new_version",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Version this update points to (display only), e.g. 3.89. "
                    "Shown in the app's update dialog when set."
                ),
                max_length=32,
            ),
        ),
    ]