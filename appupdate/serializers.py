"""Serializers for the public app-update configuration."""

from rest_framework import serializers

from .models import AppUpdateConfig


class AppUpdateConfigSerializer(serializers.ModelSerializer):
    """The exact public payload the Android app consumes.

    Only the fields the client needs are exposed — nothing sensitive.
    """

    class Meta:
        model = AppUpdateConfig
        fields = [
            "enabled",
            "mode",
            "current_version",
            "new_version",
            "new_version_code",
            "message",
            "play_store_url",
        ]