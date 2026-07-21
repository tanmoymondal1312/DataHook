"""Core DataHook models: Endpoint, Attribute and Submission."""

import secrets

from django.conf import settings
from django.db import models
from django.utils.text import slugify

from .validators import validate_attribute_key

# Alphabet for the endpoint API key — url-safe, unambiguous length of 40 chars.
_API_KEY_ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def generate_api_key() -> str:
    """Return a cryptographically secure 40-character API key."""
    return "".join(secrets.choice(_API_KEY_ALPHABET) for _ in range(40))


def _short_token(length: int = 6) -> str:
    """Short random token used to keep auto-generated slugs unique."""
    return secrets.token_hex(length)[:length]


class Endpoint(models.Model):
    """A developer-defined ingest endpoint with its own typed schema."""

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="endpoints",
    )
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=160, unique=True, blank=True)
    api_key = models.CharField(max_length=40, unique=True, default=generate_api_key)
    description = models.TextField(blank=True, default="")
    notify_on_submit = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = self._build_unique_slug()
        super().save(*args, **kwargs)

    def _build_unique_slug(self) -> str:
        base = slugify(self.name) or "endpoint"
        # Always append a short random token so slugs are unguessable and unique.
        slug = f"{base}-{_short_token()}"
        while Endpoint.objects.filter(slug=slug).exists():
            slug = f"{base}-{_short_token()}"
        return slug

    def rotate_api_key(self) -> str:
        """Regenerate and persist a fresh API key; return the new value."""
        self.api_key = generate_api_key()
        self.save(update_fields=["api_key"])
        return self.api_key

    @property
    def ingest_url(self) -> str:
        base = settings.BASE_URL.rstrip("/")
        return f"{base}/ingest/{self.slug}/"


class Attribute(models.Model):
    """A single typed field belonging to an endpoint's schema."""

    class Type(models.TextChoices):
        TEXT = "text", "Text"
        EMAIL = "email", "Email"
        NUMBER = "number", "Number"
        PHONE = "phone", "Phone"
        DATE = "date", "Date"
        BOOLEAN = "boolean", "Boolean"

    endpoint = models.ForeignKey(
        Endpoint, on_delete=models.CASCADE, related_name="attributes"
    )
    label = models.CharField(max_length=120)
    key = models.CharField(max_length=64, validators=[validate_attribute_key])
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.TEXT)
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "key"], name="unique_key_per_endpoint"
            )
        ]

    def __str__(self):
        return f"{self.endpoint.slug}:{self.key} ({self.type})"


class Submission(models.Model):
    """A stored payload posted to an endpoint's ingest URL."""

    endpoint = models.ForeignKey(
        Endpoint, on_delete=models.CASCADE, related_name="submissions"
    )
    data = models.JSONField(default=dict)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["endpoint", "-created_at"]),
        ]

    def __str__(self):
        return f"Submission #{self.pk} -> {self.endpoint.slug}"
