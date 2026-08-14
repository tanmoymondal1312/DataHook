"""Backend-controlled Android app update configuration.

A single-row table (always pk=1) that the Android app polls via
`GET /api/app-update/`. It is edited from the Django admin only, so the app's
update behaviour can be changed at runtime without shipping a new APK.

The decision is driven purely by `enabled` + `mode`; the version fields are
free-text (e.g. "2.4", "3.89") and informational/display only.
"""

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
    current_version = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=(
            "Version currently live on the Play Store (display only), "
            "e.g. 2.4."
        ),
    )
    new_version = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text=(
            "Version this update points to (display only), e.g. 3.89. Shown "
            "in the app's update dialog when set."
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

    def __str__(self):
        mode = dict(self.Mode.choices).get(self.mode, self.mode)
        return f"App update ({mode}, enabled={self.enabled})"

    @classmethod
    def load(cls) -> "AppUpdateConfig":
        """Return the single live configuration row, creating safe defaults.

        Safe defaults disable updates (mode 0), so a fresh deployment is inert
        until an admin publishes a real configuration from the admin panel.
        """
        config, _ = cls.objects.get_or_create(pk=1)
        return config