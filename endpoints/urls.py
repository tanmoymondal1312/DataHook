"""Admin API routes for endpoints and their nested resources (under /api/)."""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AllSubmissionsView,
    AttributeDetailView,
    AttributeListCreateView,
    EndpointLogoView,
    EndpointStatsView,
    EndpointViewSet,
    ExportView,
    SubmissionDetailView,
    SubmissionListView,
)

router = DefaultRouter()
router.register("endpoints", EndpointViewSet, basename="endpoint")

urlpatterns = router.urls + [
    # Cross-endpoint submission feed (all of the user's endpoints)
    path("submissions/", AllSubmissionsView.as_view(), name="all-submissions"),
    # Per-endpoint stats
    path(
        "endpoints/<int:endpoint_pk>/stats/",
        EndpointStatsView.as_view(),
        name="endpoint-stats",
    ),
    # Notification logo upload/removal
    path(
        "endpoints/<int:endpoint_pk>/logo/",
        EndpointLogoView.as_view(),
        name="endpoint-logo",
    ),
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
