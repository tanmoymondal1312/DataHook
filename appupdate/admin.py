"""Admin registration for the app-update configuration.

The configuration is a singleton row (pk=1); the admin panel is the single
place it should ever be edited. The "check" action re-validates the row, so an
invalid combination (e.g. minimum > latest) cannot be saved.
"""

from django.contrib import admin

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
                    "latest_version",
                    "minimum_version",
                    "message",
                    "play_store_url",
                ],
                "description": (
                    "Only one configuration exists (it replaces the previous "
                    "one when saved). mode 0 = no update, 1 = optional, "
                    "2 = mandatory."
                ),
            },
        ),
        ("Audit", {"fields": ["updated_at"]}),
    ]
    readonly_fields = ["updated_at"]
    list_display = ["enabled", "mode", "latest_version", "minimum_version", "updated_at"]

    def has_add_permission(self, request):
        # Singleton: there is always exactly one row (created on first read).
        return False

    def has_delete_permission(self, request, obj=None):
        return False