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
    notify_title = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Custom push-notification title. Blank falls back to "
            "'New submission · <endpoint name>'."
        ),
    )
    notify_logo = models.ImageField(
        upload_to="endpoint-logos/",
        blank=True,
        null=True,
        help_text=(
            "Optional logo shown as the notification's large icon. Uploaded "
            "via POST /api/endpoints/{id}/logo/."
        ),
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name} ({self.slug})"

    @property
    def notify_logo_url(self) -> str:
        """Absolute URL of the logo, or "" when none is set.

        Absolute because both FCM and the Android client fetch it directly —
        a relative /media/… path would be useless to them.
        """
        if not self.notify_logo:
            return ""
        from django.conf import settings

        return f"{settings.BASE_URL}{self.notify_logo.url}"

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
        IMAGE = "image", "Image URL"

    endpoint = models.ForeignKey(
        Endpoint, on_delete=models.CASCADE, related_name="attributes"
    )
    label = models.CharField(max_length=120)
    key = models.CharField(max_length=64, validators=[validate_attribute_key])
    type = models.CharField(max_length=16, choices=Type.choices, default=Type.TEXT)
    required = models.BooleanField(default=False)
    order = models.PositiveIntegerField(default=0)
    show_in_notification = models.BooleanField(
        default=False,
        help_text=(
            "Include this field's value in the push-notification body. "
            "When no attribute is selected the body stays generic. For an "
            "`image` attribute this instead supplies the notification's picture."
        ),
    )
    show_as_subtitle = models.BooleanField(
        default=False,
        help_text=(
            "Use this field's value as the notification subtitle. At most one "
            "attribute per endpoint may be the subtitle — setting it here "
            "clears the flag on the endpoint's other attributes."
        ),
    )
    show_as_data_header = models.BooleanField(
        default=False,
        help_text=(
            "For an `image` attribute: show it as the submission's header "
            "image throughout the app (detail banner, list thumbnails)."
        ),
    )

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["endpoint", "key"], name="unique_key_per_endpoint"
            )
        ]

    def __str__(self):
        return f"{self.endpoint.slug}:{self.key} ({self.type})"

    # Flags that name a single winner per endpoint: the newest one set wins and
    # the others are cleared, so the app never has to resolve a tie.
    _EXCLUSIVE_FLAGS = ("show_as_subtitle", "show_as_data_header")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        for flag in self._EXCLUSIVE_FLAGS:
            if getattr(self, flag):
                Attribute.objects.filter(
                    endpoint_id=self.endpoint_id, **{flag: True}
                ).exclude(pk=self.pk).update(**{flag: False})


def header_image_for(endpoint, data) -> str:
    """URL of the submission's header image, or "" when there is none.

    Resolves the endpoint's `show_as_data_header` image attribute against the
    submitted payload. Reads ``endpoint.attributes.all()`` so a prefetch on the
    caller's queryset keeps list views to a single extra query.
    """
    for attribute in endpoint.attributes.all():
        if attribute.type == Attribute.Type.IMAGE and attribute.show_as_data_header:
            value = (data or {}).get(attribute.key)
            return str(value).strip() if value else ""
    return ""


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
