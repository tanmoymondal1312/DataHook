"""Tests for the ingest pipeline, endpoint API and ownership isolation."""

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from .models import Attribute, Endpoint, Submission

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
            set(item), {"id", "endpoint_id", "endpoint_name", "data", "created_at"}
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
