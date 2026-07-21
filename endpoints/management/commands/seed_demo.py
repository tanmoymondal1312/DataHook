"""Create a demo user + endpoint (with attributes and a sample submission).

Idempotent: running it again reuses the demo user/endpoint. Prints the
credentials, ingest URL and API key so you can immediately test a POST.

    python manage.py seed_demo
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from endpoints.models import Attribute, Endpoint, Submission

User = get_user_model()

DEMO_EMAIL = "demo@datahook.dev"
DEMO_PASSWORD = "demo12345"

DEMO_ATTRIBUTES = [
    # (label, key, type, required, order)
    ("Full Name", "name", "text", True, 0),
    ("Email Address", "email", "email", True, 1),
    ("Phone Number", "phone", "phone", False, 2),
    ("Message", "message", "text", False, 3),
    ("Subscribe", "subscribe", "boolean", False, 4),
]


class Command(BaseCommand):
    help = "Seed a demo user and a demo 'Contact Form' endpoint for testing."

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            email=DEMO_EMAIL, defaults={"name": "Demo Developer"}
        )
        if created:
            user.set_password(DEMO_PASSWORD)
            user.save()
            self.stdout.write(self.style.SUCCESS(f"Created user {DEMO_EMAIL}"))
        else:
            self.stdout.write(f"Reusing existing user {DEMO_EMAIL}")

        endpoint, ep_created = Endpoint.objects.get_or_create(
            owner=user,
            name="Contact Form",
            defaults={"description": "Demo contact form endpoint."},
        )
        if ep_created:
            self.stdout.write(self.style.SUCCESS("Created endpoint 'Contact Form'"))
        else:
            self.stdout.write("Reusing existing endpoint 'Contact Form'")

        for label, key, atype, required, order in DEMO_ATTRIBUTES:
            Attribute.objects.get_or_create(
                endpoint=endpoint,
                key=key,
                defaults={
                    "label": label,
                    "type": atype,
                    "required": required,
                    "order": order,
                },
            )

        if not endpoint.submissions.exists():
            Submission.objects.create(
                endpoint=endpoint,
                data={
                    "name": "Ada Lovelace",
                    "email": "ada@example.com",
                    "phone": "+1 555 0100",
                    "message": "Hello from the seed command!",
                    "subscribe": True,
                },
                source_ip="127.0.0.1",
            )
            self.stdout.write(self.style.SUCCESS("Added a sample submission"))

        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("=== Demo credentials ==="))
        self.stdout.write(f"  Email:      {DEMO_EMAIL}")
        self.stdout.write(f"  Password:   {DEMO_PASSWORD}")
        self.stdout.write(f"  Endpoint:   {endpoint.name} (id={endpoint.id})")
        self.stdout.write(f"  Slug:       {endpoint.slug}")
        self.stdout.write(f"  Ingest URL: {endpoint.ingest_url}")
        self.stdout.write(f"  API Key:    {endpoint.api_key}")
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_INFO("Try it:"))
        self.stdout.write(
            f"  curl -X POST \"{endpoint.ingest_url}\" \\\n"
            f"    -H \"Content-Type: application/json\" \\\n"
            f"    -H \"X-API-Key: {endpoint.api_key}\" \\\n"
            f"    -d '{{\"name\":\"Test\",\"email\":\"t@example.com\"}}'"
        )
