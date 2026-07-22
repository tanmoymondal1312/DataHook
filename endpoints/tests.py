"""Tests for the ingest pipeline, endpoint API and ownership isolation."""

import io

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from rest_framework.test import APITestCase

from .fcm import (
    NOTIFICATION_BODY_MAX,
    NOTIFICATION_SUBTITLE_MAX,
    build_notification,
)
from .models import Attribute, Endpoint, Submission, header_image_for
from .validators import TypeValidationError, coerce_value

User = get_user_model()


class IngestTests(APITestCase):
    def setUp(self):
        self.owner = User.objects.create_user(
            email="owner@example.com", password="pw12345678", name="Owner"
        )
        self.endpoint = Endpoint.objects.create(owner=self.owner, name="Signup")
        self.endpoint.notify_on_submit = False  # no FCM in tests
        self.endpoint.save()
        Attribute.objects.create(
            endpoint=self.endpoint, label="Name", key="name", type="text",
            required=True, order=0,
        )
        Attribute.objects.create(
            endpoint=self.endpoint, label="Email", key="email", type="email",
            required=True, order=1,
        )
        Attribute.objects.create(
            endpoint=self.endpoint, label="Age", key="age", type="number",
            required=False, order=2,
        )
        self.url = reverse("ingest", kwargs={"slug": self.endpoint.slug})
        self.key = self.endpoint.api_key

    def _post(self, payload, key=None, fmt="json"):
        headers = {"HTTP_X_API_KEY": key if key is not None else self.key}
        return self.client.post(self.url, payload, format=fmt, **headers)

    def test_missing_key_rejected(self):
        r = self.client.post(self.url, {"name": "A", "email": "a@b.com"}, format="json")
        self.assertEqual(r.status_code, 401)

    def test_wrong_key_rejected(self):
        r = self._post({"name": "A", "email": "a@b.com"}, key="nope")
        self.assertEqual(r.status_code, 401)

    def test_valid_submission_stored(self):
        r = self._post({"name": "Ada", "email": "ada@example.com", "age": 36})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["success"])
        sub = Submission.objects.get(pk=r.json()["id"])
        self.assertEqual(sub.data["name"], "Ada")
        self.assertEqual(sub.data["age"], 36)  # coerced to int

    def test_missing_required_field(self):
        r = self._post({"name": "Ada"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.json()["errors"])

    def test_bad_email(self):
        r = self._post({"name": "Ada", "email": "not-email"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("email", r.json()["errors"])

    def test_bad_number(self):
        r = self._post({"name": "Ada", "email": "a@b.com", "age": "abc"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("age", r.json()["errors"])

    def test_unknown_key_rejected(self):
        r = self._post({"name": "A", "email": "a@b.com", "sneaky": "x"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("sneaky", r.json()["errors"])

    def test_form_urlencoded_accepted(self):
        r = self._post({"name": "A", "email": "a@b.com"}, fmt="multipart")
        self.assertEqual(r.status_code, 201)

    def test_boolean_and_date_coercion(self):
        Attribute.objects.create(
            endpoint=self.endpoint, label="Subscribed", key="subscribed",
            type="boolean", required=False, order=3,
        )
        Attribute.objects.create(
            endpoint=self.endpoint, label="DOB", key="dob", type="date",
            required=False, order=4,
        )
        r = self._post({
            "name": "A", "email": "a@b.com",
            "subscribed": "1", "dob": "1990-05-01",
        })
        self.assertEqual(r.status_code, 201)
        sub = Submission.objects.get(pk=r.json()["id"])
        self.assertIs(sub.data["subscribed"], True)
        self.assertEqual(sub.data["dob"], "1990-05-01")

    def test_bad_date_rejected(self):
        Attribute.objects.create(
            endpoint=self.endpoint, label="DOB", key="dob", type="date",
            required=False, order=3,
        )
        r = self._post({"name": "A", "email": "a@b.com", "dob": "31-12-1990"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("dob", r.json()["errors"])


class EndpointApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="dev@example.com", password="pw12345678", name="Dev"
        )
        self.other = User.objects.create_user(
            email="other@example.com", password="pw12345678", name="Other"
        )

    def auth(self, user):
        r = self.client.post(
            reverse("login"),
            {"email": user.email, "password": "pw12345678"},
            format="json",
        )
        token = r.json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_create_endpoint_returns_detail_with_snippets(self):
        self.auth(self.user)
        r = self.client.post(
            reverse("endpoint-list"), {"name": "Lead Form"}, format="json"
        )
        self.assertEqual(r.status_code, 201)
        body = r.json()
        self.assertIn("api_key", body)
        self.assertIn("ingest_url", body)
        self.assertIn("snippets", body)
        self.assertEqual(set(body["snippets"]), {"js_fetch", "curl", "html_form"})

    def test_rotate_key_changes_key(self):
        self.auth(self.user)
        ep = Endpoint.objects.create(owner=self.user, name="X")
        old = ep.api_key
        r = self.client.post(reverse("endpoint-rotate-key", kwargs={"pk": ep.pk}))
        self.assertEqual(r.status_code, 200)
        self.assertNotEqual(r.json()["api_key"], old)

    def test_attribute_key_validation(self):
        self.auth(self.user)
        ep = Endpoint.objects.create(owner=self.user, name="X")
        url = reverse("attribute-list", kwargs={"endpoint_pk": ep.pk})
        bad = self.client.post(
            url, {"label": "Bad", "key": "Has Space", "type": "text"}, format="json"
        )
        self.assertEqual(bad.status_code, 400)
        good = self.client.post(
            url, {"label": "Ok", "key": "ok_key", "type": "text"}, format="json"
        )
        self.assertEqual(good.status_code, 201)
        dup = self.client.post(
            url, {"label": "Dup", "key": "ok_key", "type": "text"}, format="json"
        )
        self.assertEqual(dup.status_code, 400)

    def test_ownership_isolation(self):
        ep = Endpoint.objects.create(owner=self.user, name="Private")
        self.auth(self.other)
        r = self.client.get(reverse("endpoint-detail", kwargs={"pk": ep.pk}))
        self.assertEqual(r.status_code, 404)

    def test_submission_search_and_export(self):
        self.auth(self.user)
        ep = Endpoint.objects.create(owner=self.user, name="X")
        Attribute.objects.create(
            endpoint=ep, label="Name", key="name", type="text", order=0
        )
        Submission.objects.create(endpoint=ep, data={"name": "Alice"})
        Submission.objects.create(endpoint=ep, data={"name": "Bob"})

        search = self.client.get(
            reverse("submission-list", kwargs={"endpoint_pk": ep.pk}),
            {"search": "ALICE"},
        )
        self.assertEqual(search.json()["count"], 1)

        csv = self.client.get(
            reverse("submission-export", kwargs={"endpoint_pk": ep.pk}),
            {"format": "csv"},
        )
        self.assertEqual(csv.status_code, 200)
        self.assertIn("name", csv.content.decode())


class AggregateAndStatsTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="agg@example.com", password="pw12345678", name="Agg"
        )
        self.other = User.objects.create_user(
            email="stranger@example.com", password="pw12345678", name="Stranger"
        )
        self.ep1 = Endpoint.objects.create(owner=self.user, name="Alpha")
        self.ep2 = Endpoint.objects.create(owner=self.user, name="Beta")
        self.foreign = Endpoint.objects.create(owner=self.other, name="Foreign")

        self.s1 = Submission.objects.create(endpoint=self.ep1, data={"name": "Ann"})
        self.s2 = Submission.objects.create(endpoint=self.ep2, data={"name": "Bob"})
        # A submission belonging to another user — must never leak.
        Submission.objects.create(endpoint=self.foreign, data={"name": "Zed"})

    def auth(self, user):
        r = self.client.post(
            reverse("login"),
            {"email": user.email, "password": "pw12345678"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")

    def test_aggregate_lists_only_own_submissions(self):
        self.auth(self.user)
        r = self.client.get(reverse("all-submissions"))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"count", "next", "previous", "results"})
        self.assertEqual(body["count"], 2)  # not the foreign one
        item = body["results"][0]
        self.assertEqual(
            set(item),
            {
                "id", "endpoint_id", "endpoint_name", "data", "header_image",
                "created_at",
            },
        )
        # Newest first (s2 created after s1).
        self.assertEqual(body["results"][0]["id"], self.s2.id)
        names = {row["endpoint_name"] for row in body["results"]}
        self.assertEqual(names, {"Alpha", "Beta"})

    def test_aggregate_search(self):
        self.auth(self.user)
        r = self.client.get(reverse("all-submissions"), {"search": "ANN"})
        self.assertEqual(r.json()["count"], 1)
        self.assertEqual(r.json()["results"][0]["endpoint_name"], "Alpha")

    def test_aggregate_requires_auth(self):
        r = self.client.get(reverse("all-submissions"))
        self.assertEqual(r.status_code, 401)

    def test_stats_shape_and_zero_fill(self):
        # Add a couple more submissions to ep1 for a non-trivial total.
        Submission.objects.create(endpoint=self.ep1, data={"name": "C"})
        self.auth(self.user)
        r = self.client.get(reverse("endpoint-stats", kwargs={"endpoint_pk": self.ep1.pk}))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(set(body), {"total", "today", "last_7_days", "daily"})
        self.assertEqual(body["total"], 2)  # ep1 has s1 + C
        self.assertEqual(body["today"], 2)  # both created now
        self.assertEqual(body["last_7_days"], 2)
        # 30 gap-free days, each a {date, count}, chronological, last day = today.
        self.assertEqual(len(body["daily"]), 30)
        for point in body["daily"]:
            self.assertEqual(set(point), {"date", "count"})
        self.assertEqual(body["daily"][-1]["count"], 2)
        self.assertEqual(body["daily"][0]["count"], 0)  # 29 days ago: empty
        dates = [p["date"] for p in body["daily"]]
        self.assertEqual(dates, sorted(dates))

    def test_stats_owner_only(self):
        self.auth(self.other)
        r = self.client.get(reverse("endpoint-stats", kwargs={"endpoint_pk": self.ep1.pk}))
        self.assertEqual(r.status_code, 404)


class AuthTests(APITestCase):
    def test_register_login_me(self):
        reg = self.client.post(
            reverse("register"),
            {"email": "new@example.com", "name": "New", "password": "pw12345678"},
            format="json",
        )
        self.assertEqual(reg.status_code, 201)
        self.assertIn("access", reg.json())

        login = self.client.post(
            reverse("login"),
            {"email": "new@example.com", "password": "pw12345678"},
            format="json",
        )
        self.assertEqual(login.status_code, 200)

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.json()['access']}")
        me = self.client.get(reverse("me"))
        self.assertEqual(me.status_code, 200)
        self.assertEqual(me.json()["email"], "new@example.com")

    def test_duplicate_email_rejected(self):
        User.objects.create_user(email="dup@example.com", password="pw12345678")
        r = self.client.post(
            reverse("register"),
            {"email": "dup@example.com", "name": "D", "password": "pw12345678"},
            format="json",
        )
        self.assertEqual(r.status_code, 400)


class NotificationContentTests(TestCase):
    """`build_notification` — the title/body shown for a new submission."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="notify@example.com", password="pw12345678"
        )
        self.endpoint = Endpoint.objects.create(owner=self.user, name="Contact Form")
        self.name_attr = Attribute.objects.create(
            endpoint=self.endpoint, label="Full Name", key="name",
            type="text", order=0,
        )
        self.email_attr = Attribute.objects.create(
            endpoint=self.endpoint, label="Email", key="email",
            type="email", order=1,
        )

    def make_submission(self, **data):
        return Submission.objects.create(endpoint=self.endpoint, data=data)

    # --- title ------------------------------------------------------------ #

    def test_title_defaults_to_the_endpoint_name(self):
        title = build_notification(self.endpoint, self.make_submission(name="Ada"))["title"]
        self.assertEqual(title, "New submission · Contact Form")

    def test_custom_title_is_used_when_set(self):
        self.endpoint.notify_title = "🎉 New lead!"
        title = build_notification(self.endpoint, self.make_submission(name="Ada"))["title"]
        self.assertEqual(title, "🎉 New lead!")

    def test_blank_custom_title_falls_back_to_the_default(self):
        self.endpoint.notify_title = "   "
        title = build_notification(self.endpoint, self.make_submission(name="Ada"))["title"]
        self.assertEqual(title, "New submission · Contact Form")

    # --- body ------------------------------------------------------------- #

    def test_body_is_generic_when_no_attribute_is_selected(self):
        body = build_notification(
            self.endpoint, self.make_submission(name="Ada", email="ada@example.com")
        )["body"]
        self.assertEqual(body, "New submission received")

    def test_body_shows_only_the_selected_attributes(self):
        self.name_attr.show_in_notification = True
        self.name_attr.save(update_fields=["show_in_notification"])

        body = build_notification(
            self.endpoint, self.make_submission(name="Ada", email="ada@example.com")
        )["body"]
        self.assertEqual(body, "Full Name: Ada")

    def test_multiple_selected_attributes_follow_attribute_order(self):
        # Flip `order` so the email field comes first.
        self.email_attr.order = 0
        self.email_attr.show_in_notification = True
        self.email_attr.save(update_fields=["order", "show_in_notification"])
        self.name_attr.order = 1
        self.name_attr.show_in_notification = True
        self.name_attr.save(update_fields=["order", "show_in_notification"])

        body = build_notification(
            self.endpoint, self.make_submission(name="Ada", email="ada@example.com")
        )["body"]
        self.assertEqual(body, "Email: ada@example.com · Full Name: Ada")

    def test_missing_and_empty_values_are_skipped(self):
        for attr in (self.name_attr, self.email_attr):
            attr.show_in_notification = True
            attr.save(update_fields=["show_in_notification"])

        # `email` submitted blank, `name` present.
        body = build_notification(
            self.endpoint, self.make_submission(name="Ada", email="   ")
        )["body"]
        self.assertEqual(body, "Full Name: Ada")

        # Neither usable -> generic fallback, never an empty notification.
        body = build_notification(self.endpoint, self.make_submission(email=""))["body"]
        self.assertEqual(body, "New submission received")

    def test_booleans_render_as_yes_no(self):
        flag = Attribute.objects.create(
            endpoint=self.endpoint, label="Subscribed", key="subscribed",
            type="boolean", order=2, show_in_notification=True,
        )
        body = build_notification(self.endpoint, self.make_submission(subscribed=True))["body"]
        self.assertEqual(body, "Subscribed: Yes")

        body = build_notification(self.endpoint, self.make_submission(subscribed=False))["body"]
        self.assertEqual(body, "Subscribed: No")
        self.assertTrue(flag.show_in_notification)

    def test_long_bodies_are_truncated(self):
        self.name_attr.show_in_notification = True
        self.name_attr.save(update_fields=["show_in_notification"])

        body = build_notification(self.endpoint, self.make_submission(name="x" * 500))["body"]
        self.assertLessEqual(len(body), NOTIFICATION_BODY_MAX)
        self.assertTrue(body.endswith("…"))


class NotificationSettingsApiTests(APITestCase):
    """The notification fields must survive a round-trip through the API.

    `build_notification` can be perfectly correct while the serializers never
    expose or accept these fields — that gap is invisible to the unit tests
    above, so it is covered explicitly here.
    """

    def setUp(self):
        self.user = User.objects.create_user(
            email="owner@example.com", password="pw12345678"
        )
        r = self.client.post(
            reverse("login"),
            {"email": self.user.email, "password": "pw12345678"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
        self.endpoint = Endpoint.objects.create(owner=self.user, name="Contact Form")

    def test_detail_and_list_expose_notify_title(self):
        detail = self.client.get(
            reverse("endpoint-detail", args=[self.endpoint.id])
        ).json()
        self.assertIn("notify_title", detail)
        self.assertEqual(detail["notify_title"], "")

        listed = self.client.get(reverse("endpoint-list")).json()
        self.assertIn("notify_title", listed[0])

    def test_patch_sets_and_clears_notify_title(self):
        url = reverse("endpoint-detail", args=[self.endpoint.id])

        r = self.client.patch(url, {"notify_title": "New lead!"}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notify_title"], "New lead!")
        self.endpoint.refresh_from_db()
        self.assertEqual(self.endpoint.notify_title, "New lead!")

        r = self.client.patch(url, {"notify_title": ""}, format="json")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notify_title"], "")

    def test_notify_title_is_length_limited(self):
        r = self.client.patch(
            reverse("endpoint-detail", args=[self.endpoint.id]),
            {"notify_title": "x" * 101},
            format="json",
        )
        self.assertEqual(r.status_code, 400)

    def test_attribute_show_in_notification_round_trips(self):
        list_url = reverse("attribute-list", args=[self.endpoint.id])

        r = self.client.post(
            list_url,
            {
                "label": "Full Name", "key": "name", "type": "text",
                "required": True, "order": 0, "show_in_notification": True,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertTrue(r.json()["show_in_notification"])
        attribute_id = r.json()["id"]

        # Present on read...
        listed = self.client.get(list_url).json()
        self.assertTrue(listed[0]["show_in_notification"])

        # ...and on the endpoint detail's nested attributes.
        detail = self.client.get(
            reverse("endpoint-detail", args=[self.endpoint.id])
        ).json()
        self.assertTrue(detail["attributes"][0]["show_in_notification"])

        # ...and togglable.
        r = self.client.patch(
            reverse("attribute-detail", args=[self.endpoint.id, attribute_id]),
            {"show_in_notification": False},
            format="json",
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["show_in_notification"])

    def test_attribute_defaults_to_not_shown(self):
        r = self.client.post(
            reverse("attribute-list", args=[self.endpoint.id]),
            {"label": "Email", "key": "email", "type": "email", "required": False},
            format="json",
        )
        self.assertEqual(r.status_code, 201)
        self.assertFalse(r.json()["show_in_notification"])


class NotificationVisualTests(TestCase):
    """Subtitle, notification image and logo — the visual extras."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="visual@example.com", password="pw12345678"
        )
        self.endpoint = Endpoint.objects.create(owner=self.user, name="Contact Form")
        self.name_attr = Attribute.objects.create(
            endpoint=self.endpoint, label="Full Name", key="name", type="text", order=0,
        )
        self.photo_attr = Attribute.objects.create(
            endpoint=self.endpoint, label="Photo", key="photo", type="image", order=1,
        )

    def build(self, **data):
        submission = Submission.objects.create(endpoint=self.endpoint, data=data)
        return build_notification(self.endpoint, submission)

    # --- subtitle --------------------------------------------------------- #

    def test_subtitle_is_empty_by_default(self):
        self.assertEqual(self.build(name="Ada")["subtitle"], "")

    def test_subtitle_is_the_bare_value_without_a_label(self):
        self.name_attr.show_as_subtitle = True
        self.name_attr.save()
        self.assertEqual(self.build(name="Ada")["subtitle"], "Ada")

    def test_subtitle_is_truncated(self):
        self.name_attr.show_as_subtitle = True
        self.name_attr.save()
        subtitle = self.build(name="y" * 200)["subtitle"]
        self.assertLessEqual(len(subtitle), NOTIFICATION_SUBTITLE_MAX)
        self.assertTrue(subtitle.endswith("…"))

    def test_only_one_attribute_can_be_the_subtitle(self):
        self.name_attr.show_as_subtitle = True
        self.name_attr.save()
        self.photo_attr.show_as_subtitle = True
        self.photo_attr.save()

        self.name_attr.refresh_from_db()
        self.assertFalse(self.name_attr.show_as_subtitle)
        self.assertTrue(Attribute.objects.get(pk=self.photo_attr.pk).show_as_subtitle)

    # --- image ------------------------------------------------------------ #

    def test_image_attribute_supplies_the_picture_not_the_body(self):
        self.photo_attr.show_in_notification = True
        self.photo_attr.save()
        self.name_attr.show_in_notification = True
        self.name_attr.save()

        content = self.build(name="Ada", photo="https://example.com/a.jpg")
        self.assertEqual(content["image_url"], "https://example.com/a.jpg")
        # The raw URL must not pollute the body text.
        self.assertEqual(content["body"], "Full Name: Ada")

    def test_image_is_empty_when_not_flagged_or_not_submitted(self):
        self.assertEqual(self.build(photo="https://example.com/a.jpg")["image_url"], "")

        self.photo_attr.show_in_notification = True
        self.photo_attr.save()
        self.assertEqual(self.build(name="Ada")["image_url"], "")

    # --- logo ------------------------------------------------------------- #

    def test_logo_url_is_empty_without_an_upload(self):
        self.assertEqual(self.build(name="Ada")["logo_url"], "")

    def test_logo_url_is_absolute(self):
        self.endpoint.notify_logo = "endpoint-logos/example.png"
        self.endpoint.save(update_fields=["notify_logo"])
        logo = self.build(name="Ada")["logo_url"]
        self.assertTrue(logo.startswith(settings.BASE_URL), logo)
        self.assertIn("/media/endpoint-logos/example.png", logo)

    # --- data header ------------------------------------------------------ #

    def test_header_image_resolves_only_for_a_flagged_image_attribute(self):
        submission = Submission.objects.create(
            endpoint=self.endpoint, data={"photo": "https://example.com/h.jpg"}
        )
        self.assertEqual(header_image_for(self.endpoint, submission.data), "")

        self.photo_attr.show_as_data_header = True
        self.photo_attr.save()
        self.endpoint.refresh_from_db()
        self.assertEqual(
            header_image_for(self.endpoint, submission.data),
            "https://example.com/h.jpg",
        )

    def test_only_one_attribute_can_be_the_data_header(self):
        second = Attribute.objects.create(
            endpoint=self.endpoint, label="Cover", key="cover", type="image", order=2,
        )
        self.photo_attr.show_as_data_header = True
        self.photo_attr.save()
        second.show_as_data_header = True
        second.save()

        self.photo_attr.refresh_from_db()
        self.assertFalse(self.photo_attr.show_as_data_header)


class ImageAttributeTypeTests(TestCase):
    """The `image` attribute type validates URLs at ingest."""

    def test_accepts_http_and_https_urls(self):
        self.assertEqual(
            coerce_value("image", "https://example.com/a.png"),
            "https://example.com/a.png",
        )
        self.assertEqual(
            coerce_value("image", " http://example.com/b.jpg "),
            "http://example.com/b.jpg",
        )

    def test_rejects_non_urls_and_other_schemes(self):
        for bad in ("not a url", "example.com/a.png", "ftp://example.com/a.png",
                    "javascript:alert(1)", "data:image/png;base64,AAAA"):
            with self.assertRaises(TypeValidationError, msg=bad):
                coerce_value("image", bad)


class LogoUploadApiTests(APITestCase):
    """POST/DELETE /api/endpoints/{id}/logo/ — multipart upload of the logo."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="logo@example.com", password="pw12345678"
        )
        r = self.client.post(
            reverse("login"),
            {"email": self.user.email, "password": "pw12345678"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
        self.endpoint = Endpoint.objects.create(owner=self.user, name="Contact Form")
        self.url = reverse("endpoint-logo", args=[self.endpoint.id])

    @staticmethod
    def png_upload(name="logo.png", size=(8, 8)):
        buffer = io.BytesIO()
        Image.new("RGB", size, "red").save(buffer, format="PNG")
        buffer.seek(0)
        return SimpleUploadedFile(name, buffer.read(), content_type="image/png")

    def test_upload_sets_an_absolute_logo_url(self):
        r = self.client.post(self.url, {"logo": self.png_upload()}, format="multipart")
        self.assertEqual(r.status_code, 200)

        logo_url = r.json()["notify_logo_url"]
        self.assertTrue(logo_url.startswith(settings.BASE_URL), logo_url)
        self.assertIn("/media/endpoint-logos/", logo_url)

        self.endpoint.refresh_from_db()
        self.assertTrue(self.endpoint.notify_logo)

    def test_detail_exposes_logo_url_and_defaults_to_blank(self):
        detail = self.client.get(
            reverse("endpoint-detail", args=[self.endpoint.id])
        ).json()
        self.assertEqual(detail["notify_logo_url"], "")

    def test_delete_clears_the_logo(self):
        self.client.post(self.url, {"logo": self.png_upload()}, format="multipart")
        r = self.client.delete(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["notify_logo_url"], "")

        self.endpoint.refresh_from_db()
        self.assertFalse(self.endpoint.notify_logo)

    def test_rejects_a_missing_file(self):
        r = self.client.post(self.url, {}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_rejects_a_disallowed_content_type(self):
        bad = SimpleUploadedFile("logo.gif", b"GIF89a", content_type="image/gif")
        r = self.client.post(self.url, {"logo": bad}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_rejects_an_oversized_file(self):
        big = SimpleUploadedFile(
            "big.png", b"x" * (settings.LOGO_MAX_BYTES + 1), content_type="image/png"
        )
        r = self.client.post(self.url, {"logo": big}, format="multipart")
        self.assertEqual(r.status_code, 400)

    def test_another_user_cannot_touch_the_logo(self):
        other = User.objects.create_user(email="other@example.com", password="pw12345678")
        r = self.client.post(
            reverse("login"),
            {"email": other.email, "password": "pw12345678"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
        r = self.client.post(self.url, {"logo": self.png_upload()}, format="multipart")
        self.assertEqual(r.status_code, 404)


class VisualFlagsApiTests(APITestCase):
    """The new attribute flags must round-trip through the API."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="flags@example.com", password="pw12345678"
        )
        r = self.client.post(
            reverse("login"),
            {"email": self.user.email, "password": "pw12345678"},
            format="json",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {r.json()['access']}")
        self.endpoint = Endpoint.objects.create(owner=self.user, name="Contact Form")
        self.list_url = reverse("attribute-list", args=[self.endpoint.id])

    def test_image_attribute_with_all_flags_round_trips(self):
        r = self.client.post(
            self.list_url,
            {
                "label": "Photo", "key": "photo", "type": "image",
                "required": False, "order": 0,
                "show_in_notification": True,
                "show_as_subtitle": True,
                "show_as_data_header": True,
            },
            format="json",
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual(body["type"], "image")
        self.assertTrue(body["show_in_notification"])
        self.assertTrue(body["show_as_subtitle"])
        self.assertTrue(body["show_as_data_header"])

        listed = self.client.get(self.list_url).json()[0]
        self.assertTrue(listed["show_as_data_header"])

    def test_flags_default_to_false(self):
        r = self.client.post(
            self.list_url,
            {"label": "Name", "key": "name", "type": "text", "required": False},
            format="json",
        )
        body = r.json()
        self.assertFalse(body["show_as_subtitle"])
        self.assertFalse(body["show_as_data_header"])

    def test_setting_subtitle_on_a_second_attribute_clears_the_first(self):
        first = self.client.post(
            self.list_url,
            {"label": "Name", "key": "name", "type": "text", "required": False,
             "order": 0, "show_as_subtitle": True},
            format="json",
        ).json()
        self.client.post(
            self.list_url,
            {"label": "Email", "key": "email", "type": "email", "required": False,
             "order": 1, "show_as_subtitle": True},
            format="json",
        )

        listed = {a["key"]: a for a in self.client.get(self.list_url).json()}
        self.assertFalse(listed["name"]["show_as_subtitle"])
        self.assertTrue(listed["email"]["show_as_subtitle"])
        self.assertEqual(listed["name"]["id"], first["id"])

    def test_submission_exposes_header_image(self):
        self.client.post(
            self.list_url,
            {"label": "Photo", "key": "photo", "type": "image", "required": False,
             "order": 0, "show_as_data_header": True},
            format="json",
        )
        Submission.objects.create(
            endpoint=self.endpoint, data={"photo": "https://example.com/x.jpg"}
        )
        results = self.client.get(
            reverse("submission-list", args=[self.endpoint.id])
        ).json()["results"]
        self.assertEqual(results[0]["header_image"], "https://example.com/x.jpg")
