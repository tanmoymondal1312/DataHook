"""Admin registration for the app-update configuration.

The configuration is a singleton row (pk=1); the admin panel is the single
place it should ever be edited. The "check" action re-validates the row, so an
invalid combination (e.g. minimum > latest) cannot be saved.
"""

from django.contrib import admin
from django.urls import reverse

from .models import AppUpdateConfig


@admin.register(AppUpdateConfig)
class AppUpdateConfigAdmin(admin.ModelAdmin):
    fieldsets = [
        (
            "Update behaviour",
            {
                "fields": [
                    "enabled",
                    "mode",
                    "current_version",
                    "new_version",
                    "new_version_code",
                    "message",
                    "play_store_url",
                ],
                "description": (
                    "Only one configuration exists (it replaces the previous "
                    "one when saved). mode 0 = no update, 1 = optional, "
                    "2 = mandatory. Version text fields are display-only; the "
                    "prompt is gated by enabled + mode + new_version_code: "
                    "users whose installed versionCode is below new_version_code "
                    "are prompted, everyone else never sees it — so users who "
                    "already updated stop being prompted automatically."
                ),
            },
        ),
        ("Audit", {"fields": ["updated_at"]}),
    ]
    readonly_fields = ["updated_at"]
    list_display = ["enabled", "mode", "current_version", "new_version", "updated_at"]
    # Don't link any column: the whole row is clickable instead (see the custom
    # change_list template), so the Enabled/Disabled icon stays a pure status
    # indicator rather than a link.
    list_display_links = None

    def has_add_permission(self, request):
        # Singleton: there is always exactly one row (created on first read).
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Expose the deterministic change URL for the row-click script. Because
        # this is a singleton, the target is always the same object.
        extra_context = extra_context or {}
        config = AppUpdateConfig.load()
        extra_context["config_change_url"] = reverse(
            "admin:appupdate_appupdateconfig_change", args=[config.pk]
        )
        return super().changelist_view(request, extra_context=extra_context)