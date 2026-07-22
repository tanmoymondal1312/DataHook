"""Tests for Google sign-in (`POST /api/auth/google/`).

The Google token check itself is patched out — these cover our own rules:
account merging, name backfill, and the failure envelopes.
"""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

User = get_user_model()

WEB_CLIENT_ID = "test-web-client-id.apps.googleusercontent.com"

VERIFY_TARGET = "accounts.serializers.google_id_token.verify_oauth2_token"


def google_claims(**overrides):
    """A minimal set of claims as returned by Google's verifier."""
    claims = {
        "iss": "https://accounts.google.com",
        "aud": WEB_CLIENT_ID,
        "sub": "1234567890",
        "email": "ada@example.com",
        "email_verified": True,
        "name": "Ada Lovelace",
    }
    claims.update(overrides)
    return claims


@override_settings(GOOGLE_WEB_CLIENT_ID=WEB_CLIENT_ID)
class GoogleAuthTests(TestCase):
    def setUp(self):
        self.url = reverse("google-auth")

    def post(self, token="dummy-id-token"):
        return self.client.post(
            self.url, {"id_token": token}, content_type="application/json"
        )

    # --- happy paths ------------------------------------------------------ #

    def test_creates_account_on_first_google_sign_in(self):
        with patch(VERIFY_TARGET, return_value=google_claims()):
            response = self.post()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["user"]["email"], "ada@example.com")
        self.assertEqual(body["user"]["name"], "Ada Lovelace")
        self.assertIn("access", body)
        self.assertIn("refresh", body)

        user = User.objects.get(email="ada@example.com")
        self.assertFalse(user.has_usable_password())

    def test_second_sign_in_reuses_the_same_account(self):
        with patch(VERIFY_TARGET, return_value=google_claims()):
            self.post()
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
        self.assertEqual(User.objects.filter(email="ada@example.com").count(), 1)

    def test_merges_into_existing_password_account(self):
        """Same email via password then Google = one account, not two."""
        existing = User.objects.create_user(
            email="ada@example.com", password="secret12345", name="Ada"
        )

        with patch(VERIFY_TARGET, return_value=google_claims()):
            response = self.post()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["created"])
        self.assertEqual(response.json()["user"]["id"], existing.id)
        self.assertEqual(User.objects.count(), 1)

        # The password still works — Google login must not lock them out.
        existing.refresh_from_db()
        self.assertTrue(existing.check_password("secret12345"))

    def test_email_is_matched_case_insensitively(self):
        existing = User.objects.create_user(
            email="ada@example.com", password="secret12345"
        )

        with patch(VERIFY_TARGET, return_value=google_claims(email="ADA@Example.com")):
            response = self.post()

        self.assertEqual(response.json()["user"]["id"], existing.id)
        self.assertEqual(User.objects.count(), 1)

    def test_backfills_a_missing_name_but_never_overwrites_one(self):
        blank = User.objects.create_user(email="ada@example.com", password="x" * 12)
        with patch(VERIFY_TARGET, return_value=google_claims()):
            self.post()
        blank.refresh_from_db()
        self.assertEqual(blank.name, "Ada Lovelace")

        chosen = User.objects.create_user(
            email="grace@example.com", password="x" * 12, name="Grace H."
        )
        with patch(VERIFY_TARGET, return_value=google_claims(email="grace@example.com")):
            self.post()
        chosen.refresh_from_db()
        self.assertEqual(chosen.name, "Grace H.")

    # --- failure paths ---------------------------------------------------- #

    def test_rejects_an_invalid_token(self):
        with patch(VERIFY_TARGET, side_effect=ValueError("bad signature")):
            response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_rejects_an_untrusted_issuer(self):
        with patch(VERIFY_TARGET, return_value=google_claims(iss="evil.example.com")):
            response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_rejects_an_unverified_email(self):
        with patch(VERIFY_TARGET, return_value=google_claims(email_verified=False)):
            response = self.post()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)

    def test_rejects_a_disabled_account(self):
        User.objects.create_user(
            email="ada@example.com", password="x" * 12, is_active=False
        )
        with patch(VERIFY_TARGET, return_value=google_claims()):
            response = self.post()

        self.assertEqual(response.status_code, 400)

    def test_requires_the_id_token_field(self):
        response = self.client.post(self.url, {}, content_type="application/json")
        self.assertEqual(response.status_code, 400)

    @override_settings(GOOGLE_WEB_CLIENT_ID="")
    def test_returns_400_when_the_server_is_not_configured(self):
        response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(User.objects.count(), 0)
