"""Auth + device routes (mounted under /api/)."""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import DeviceView, GoogleAuthView, LoginView, MeView, RegisterView

urlpatterns = [
    path("auth/register/", RegisterView.as_view(), name="register"),
    path("auth/login/", LoginView.as_view(), name="login"),
    path("auth/google/", GoogleAuthView.as_view(), name="google-auth"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/me/", MeView.as_view(), name="me"),
    path("devices/", DeviceView.as_view(), name="devices"),
]
