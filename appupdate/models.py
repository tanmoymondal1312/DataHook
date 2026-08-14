"""Backend-controlled Android app update configuration.

A single-row table (always pk=1) that the Android app polls via
`GET /api/app-update/`. It is edited from the Django admin only, so the app's
update behaviour can be changed at runtime without shipping a new APK.
"""

from django.core.exceptions import ValidationError
from django.db import models


class AppUpdateConfig(models.Model):
    """The one live app-update configuration (singleton row, pk=1)."""

    class Mode(models.IntegerChoices):
        NONE = 0, "No update"
        OPTIONAL = 1, "Optional update"
        MANDATORY = 2, "Mandatory update"

    enabled = models.BooleanField(
        default=False,
        help_text="Master switch. When off, clients never see an update prompt.",
    )
    mode = models.PositiveSmallIntegerField(
        choices=Mode.choices,
        default=Mode.NONE,
        help_text=(
            "0 = no update, 1 = optional (user can skip), "
            "2 = mandatory (user must update to continue)."
        ),
    )
    latest_version = models.PositiveIntegerField(
        default=1,
        help_text=(
            "Latest published versionCode. Optional mode prompts users with a "
            "lower versionCode than this."
        ),
    )
    minimum_version = models.PositiveIntegerField(
        default=1,
        help_text=(
            "Minimum supported versionCode. Mandatory mode blocks users below "
            "this version."
        ),
    )
    message = models.TextField(
        default=(
            "A new version of the app is available. Please update to get the "
            "latest features and improvements."
        ),
        help_text="Shown verbatim in the app's update dialog.",
    )
    play_store_url = models.URLField(
        blank=True,
        default="",
        help_text=(
            "Play Store listing URL opened by the Update button. Blank falls "
            "back to the app's Play Store page built from its package name."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(latest_version__gte=models.F("minimum_version")),
                name="latest_version_gte_minimum_version",
            ),
        ]

    def __str__(self):
        mode = dict(self.Mode.choices).get(self.mode, self.mode)
        return f"App update ({mode}, enabled={self.enabled})"

    def clean(self):
        super().clean()
        if self.latest_version < self.minimum_version:
            raise ValidationError(
                {
                    "latest_version": (
                        "Latest version must be greater than or equal to the "
                        "minimum version."
                    )
                }
            )

    @classmethod
    def load(cls) -> "AppUpdateConfig":
        """Return the single live configuration row, creating safe defaults.

        Safe defaults disable updates (mode 0), so a fresh deployment is inert
        until an admin publishes a real configuration from the admin panel.
        """
        config, _ = cls.objects.get_or_create(pk=1)
        return config