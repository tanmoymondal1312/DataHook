"""Routes for the app-update configuration (mounted under /api/)."""

from django.urls import path

from .views import AppUpdateView

urlpatterns = [
    path("app-update/", AppUpdateView.as_view(), name="app-update"),
]