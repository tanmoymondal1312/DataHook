"""Backend-controlled Android app update configuration.

A single-row table (always pk=1) that the Android app polls via
`GET /api/app-update/`. It is edited from the Django admin only, so the app's
update behaviour can be changed at runtime without shipping a new APK.

The prompt is gated by `enabled` + `mode` + the installed versionCode:

  * The Android app reports its own installed versionCode (the build
    number, e.g. 3) and compares it against `new_version_code`.
  * Installed >= new_version_code → the app is already on (or past) the
    target release → never prompted. This is what stops users who just
    updated from seeing the dialog again.
  * Installed < new_version_code → prompted only when `enabled` is on:
    mode 1 = optional, mode 2 = mandatory.

`current_version` / `new_version` are free-text (e.g. "2.4", "3.89") and
informational/display only.
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
    new_version_code = models.PositiveIntegerField(
        default=0,
        help_text=(
            "The versionCode (build number) of the release this update points "
            "to, e.g. 4. The app compares its own installed versionCode "
            "against this: lower → prompt, equal or higher → never prompt "
            "(users who already updated see nothing). Bump this every time "
            "you publish a release. 0 = never prompt (safe default)."
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