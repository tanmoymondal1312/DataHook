"""Auth, current-user and device-registration API views."""

from rest_framework import status
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenRefreshView  # noqa: F401 (re-export)

from .models import Device
from .serializers import (
    DeviceSerializer,
    GoogleAuthSerializer,
    LoginSerializer,
    RegisterSerializer,
    UserSerializer,
    tokens_for,
)


class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(
            {"user": UserSerializer(user).data, **tokens_for(user)},
            status=status.HTTP_201_CREATED,
        )


class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        return Response(
            {"user": UserSerializer(user).data, **tokens_for(user)},
            status=status.HTTP_200_OK,
        )


class GoogleAuthView(APIView):
    """Sign in (or sign up) with a Google ID token.

    Returns the same envelope as login/register plus ``created``, so the client
    can tell a brand-new account from an existing one.
    """

    permission_classes = [AllowAny]
    throttle_scope = "auth"

    def post(self, request):
        serializer = GoogleAuthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        created = serializer.validated_data["created"]
        return Response(
            {"user": UserSerializer(user).data, "created": created, **tokens_for(user)},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class MeView(RetrieveAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user


class DeviceView(APIView):
    """Upsert (POST) or remove (DELETE) an FCM device for the current user."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["fcm_token"]
        platform = serializer.validated_data.get("platform", "android")

        # A token uniquely identifies a physical device; if it already exists
        # (even under another user, e.g. after account switch) reassign it.
        device, _created = Device.objects.update_or_create(
            fcm_token=token,
            defaults={"owner": request.user, "platform": platform},
        )
        return Response(
            {
                "id": device.id,
                "fcm_token": device.fcm_token,
                "platform": device.platform,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request):
        serializer = DeviceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        token = serializer.validated_data["fcm_token"]
        Device.objects.filter(owner=request.user, fcm_token=token).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
