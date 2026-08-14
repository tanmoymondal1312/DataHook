"""Tests for the public app-update endpoint and its configuration rules."""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import AppUpdateConfig


class AppUpdateAdminTests(TestCase):
    """The changelist must open the config from anywhere on the row, while the
    Enabled/Disabled icon stays a plain status indicator (no link)."""

    def setUp(self):
        user = get_user_model().objects.create_user(
            email="admin@example.com", password="pw12345678"
        )
        user.is_staff = True
        user.is_superuser = True
        user.save()
        self.client.force_login(user)
        self.config = AppUpdateConfig.load()

    def test_changelist_renders_without_links(self):
        r = self.client.get(reverse("admin:appupdate_appupdateconfig_changelist"))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        # The Enabled/Disabled icon cell must not contain any link.
        self.assertIn('class="field-enabled"', html)
        self.assertNotIn('<a href', html[html.index('class="field-enabled"'):][:200])

    def test_changelist_injects_row_click_url(self):
        r = self.client.get(reverse("admin:appupdate_appupdateconfig_changelist"))
        html = r.content.decode()
        self.assertIn("config-change-url", html)
        self.assertIn(f'/admin/appupdate/appupdateconfig/{self.config.pk}/change/', html)

    def test_change_page_still_opens(self):
        r = self.client.get(
            reverse("admin:appupdate_appupdateconfig_change", args=[self.config.pk])
        )
        self.assertEqual(r.status_code, 200)


class AppUpdateApiTests(APITestCase):
    def get_config(self):
        return self.client.get(reverse("app-update"))

    def test_public_without_authentication(self):
        """The Android app polls this before login — auth must not be required."""
        r = self.get_config()
        self.assertEqual(r.status_code, 200)

    def test_default_config_is_inert(self):
        """Fresh deployments must not prompt anyone until an admin enables it."""
        body = self.get_config().json()
        self.assertIs(body["enabled"], False)
        self.assertEqual(body["mode"], 0)
        self.assertEqual(
            set(body),
            {
                "enabled", "mode", "current_version", "new_version",
                "message", "play_store_url",
            },
        )

    def test_config_values_round_trip(self):
        config = AppUpdateConfig.load()
        config.enabled = True
        config.mode = 1
        config.current_version = "2.4"
        config.new_version = "3.89"
        config.message = "Please update!"
        config.play_store_url = (
            "https://play.google.com/store/apps/details?id=com.mediaghor.datahook"
        )
        config.save()
        body = self.get_config().json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["mode"], 1)
        self.assertEqual(body["current_version"], "2.4")
        self.assertEqual(body["new_version"], "3.89")
        self.assertEqual(body["message"], "Please update!")
        self.assertIn("play.google.com", body["play_store_url"])

    def test_version_fields_accept_any_string(self):
        """Versions are display-only text; any value is valid."""
        config = AppUpdateConfig.load()
        config.current_version = "1.0"
        config.new_version = "3.89 beta"
        config.full_clean()  # must not raise
        config.save()

    def test_single_row_never_recreated(self):
        AppUpdateConfig.load()
        AppUpdateConfig.load()
        self.assertEqual(AppUpdateConfig.objects.count(), 1)


class AppUpdateValidationTests(TestCase):
    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValidationError):
            AppUpdateConfig(pk=1, mode=9).full_clean()

    def test_valid_modes_accepted(self):
        for mode in (0, 1, 2):
            AppUpdateConfig(pk=1, mode=mode).full_clean()  # must not raise

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValidationError):
            AppUpdateConfig(pk=1, mode=0, play_store_url="not a url").full_clean()