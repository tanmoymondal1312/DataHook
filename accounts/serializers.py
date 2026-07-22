"""Serializers for auth, the current user profile and push devices."""

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Device

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """Public representation of a user (never exposes the password)."""

    class Meta:
        model = User
        fields = ["id", "email", "name", "date_joined"]
        read_only_fields = fields


def tokens_for(user) -> dict:
    """Issue an access/refresh pair for ``user``."""
    refresh = RefreshToken.for_user(user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    name = serializers.CharField(max_length=150, allow_blank=True, required=False)
    password = serializers.CharField(write_only=True, min_length=8)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError(
                "A user with this email already exists."
            )
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        return User.objects.create_user(
            email=validated_data["email"],
            password=validated_data["password"],
            name=validated_data.get("name", ""),
        )


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["email"].strip().lower(),
            password=attrs["password"],
        )
        if not user:
            raise serializers.ValidationError(
                "Invalid email or password.", code="authorization"
            )
        if not user.is_active:
            raise serializers.ValidationError(
                "This account is disabled.", code="authorization"
            )
        attrs["user"] = user
        return attrs


GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


class GoogleAuthSerializer(serializers.Serializer):
    """Exchange a Google ID token for a DataHook user + JWT pair.

    The Android client obtains the token through Credential Manager using the
    project's **Web** client ID as `serverClientId`, so the token's audience is
    ``settings.GOOGLE_WEB_CLIENT_ID``. Accounts are matched on the verified
    email: an existing password account with that address is reused (the two
    sign-in methods share one account) rather than duplicated.
    """

    id_token = serializers.CharField(write_only=True)

    def validate_id_token(self, value):
        if not settings.GOOGLE_WEB_CLIENT_ID:
            raise serializers.ValidationError(
                "Google sign-in is not configured on this server."
            )
        try:
            claims = google_id_token.verify_oauth2_token(
                value, google_requests.Request(), settings.GOOGLE_WEB_CLIENT_ID
            )
        except ValueError:
            # Covers a bad signature, wrong audience and an expired token.
            raise serializers.ValidationError("Invalid or expired Google token.")

        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise serializers.ValidationError("Untrusted Google token issuer.")
        if not claims.get("email"):
            raise serializers.ValidationError("Google account has no email address.")
        if not claims.get("email_verified"):
            raise serializers.ValidationError("This Google email is not verified.")
        return claims

    def validate(self, attrs):
        claims = attrs["id_token"]
        email = claims["email"].strip().lower()
        google_name = (claims.get("name") or "").strip()

        user = User.objects.filter(email__iexact=email).first()
        created = user is None
        if created:
            # No password is set, so this account can only sign in with Google
            # until the user sets one (create_user(password=None) marks the
            # password unusable).
            user = User.objects.create_user(
                email=email, password=None, name=google_name
            )
        elif google_name and not user.name:
            # Fill in a name we previously did not have; never overwrite one
            # the user chose themselves.
            user.name = google_name
            user.save(update_fields=["name"])

        if not user.is_active:
            raise serializers.ValidationError(
                "This account is disabled.", code="authorization"
            )

        attrs["user"] = user
        attrs["created"] = created
        return attrs


class DeviceSerializer(serializers.Serializer):
    """Upsert/delete a device by FCM token for the current user."""

    fcm_token = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(
        choices=Device.PLATFORM_CHOICES, required=False, default="android"
    )
