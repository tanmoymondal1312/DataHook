"""Tests for the public app-update endpoint and its configuration rules."""

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import AppUpdateConfig


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
        self.assertIsInstance(body["latest_version"], int)
        self.assertIsInstance(body["minimum_version"], int)
        self.assertEqual(
            set(body),
            {
                "enabled", "mode", "latest_version", "minimum_version",
                "message", "play_store_url",
            },
        )

    def test_config_values_round_trip(self):
        config = AppUpdateConfig.load()
        config.enabled = True
        config.mode = 1
        config.latest_version = 12
        config.minimum_version = 10
        config.message = "Please update!"
        config.play_store_url = (
            "https://play.google.com/store/apps/details?id=com.mediaghor.datahook"
        )
        config.save()
        body = self.get_config().json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["mode"], 1)
        self.assertEqual(body["latest_version"], 12)
        self.assertEqual(body["minimum_version"], 10)
        self.assertEqual(body["message"], "Please update!")
        self.assertIn("play.google.com", body["play_store_url"])

    def test_single_row_never_recreated(self):
        AppUpdateConfig.load()
        AppUpdateConfig.load()
        self.assertEqual(AppUpdateConfig.objects.count(), 1)


class AppUpdateValidationTests(TestCase):
    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValidationError):
            AppUpdateConfig(pk=1, mode=9, latest_version=1, minimum_version=1).full_clean()

    def test_minimum_greater_than_latest_rejected(self):
        with self.assertRaises(ValidationError):
            AppUpdateConfig(
                pk=1, mode=1, latest_version=10, minimum_version=12
            ).full_clean()

    def test_latest_greater_than_or_equal_minimum_accepted(self):
        config = AppUpdateConfig(
            pk=1, mode=2, latest_version=12, minimum_version=12
        )
        config.full_clean()  # must not raise

    def test_negative_versions_rejected(self):
        with self.assertRaises(ValidationError):
            AppUpdateConfig(
                pk=1, mode=0, latest_version=-1, minimum_version=1
            ).full_clean()

    def test_invalid_url_rejected(self):
        with self.assertRaises(ValidationError):
            AppUpdateConfig(
                pk=1, mode=0, latest_version=1, minimum_version=1,
                play_store_url="not a url",
            ).full_clean()