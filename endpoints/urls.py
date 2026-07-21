"""Admin API routes for endpoints and their nested resources (under /api/)."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AttributeDetailView,
    AttributeListCreateView,
    EndpointViewSet,
    ExportView,
    SubmissionDetailView,
    SubmissionListView,
)

router = DefaultRouter()
router.register("endpoints", EndpointViewSet, basename="endpoint")

urlpatterns = router.urls + [
    # Nested attributes
    path(
        "endpoints/<int:endpoint_pk>/attributes/",
        AttributeListCreateView.as_view(),
        name="attribute-list",
    ),
    path(
        "endpoints/<int:endpoint_pk>/attributes/<int:pk>/",
        AttributeDetailView.as_view(),
        name="attribute-detail",
    ),
    # Nested submissions
    path(
        "endpoints/<int:endpoint_pk>/submissions/",
        SubmissionListView.as_view(),
        name="submission-list",
    ),
    path(
        "endpoints/<int:endpoint_pk>/submissions/<int:pk>/",
        SubmissionDetailView.as_view(),
        name="submission-detail",
    ),
    # Export
    path(
        "endpoints/<int:endpoint_pk>/export/",
        ExportView.as_view(),
        name="submission-export",
    ),
]
