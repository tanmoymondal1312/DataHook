"""Account models: the email-login custom User and push Device."""

from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user that logs in with an email address (no username)."""

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=150, blank=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["-date_joined"]

    def __str__(self):
        return self.email

    def get_full_name(self):
        return self.name or self.email

    def get_short_name(self):
        return self.name or self.email.split("@")[0]


class Device(models.Model):
    """An FCM registration token for a user's device (push delivery target)."""

    PLATFORM_CHOICES = [
        ("android", "Android"),
        ("ios", "iOS"),
        ("web", "Web"),
    ]

    owner = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="devices"
    )
    fcm_token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(
        max_length=16, choices=PLATFORM_CHOICES, default="android"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.owner.email} · {self.platform} · {self.fcm_token[:12]}…"
