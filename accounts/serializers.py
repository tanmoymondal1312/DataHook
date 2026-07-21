"""Serializers for auth, the current user profile and push devices."""

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
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


class DeviceSerializer(serializers.Serializer):
    """Upsert/delete a device by FCM token for the current user."""

    fcm_token = serializers.CharField(max_length=255)
    platform = serializers.ChoiceField(
        choices=Device.PLATFORM_CHOICES, required=False, default="android"
    )
