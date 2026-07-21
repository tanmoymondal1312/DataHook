"""Admin API viewsets: endpoints, nested attributes, submissions and export."""

import csv
import json

from django.db.models import Count, TextField
from django.db.models.functions import Cast
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateDestroyAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Attribute, Endpoint, Submission
from .pagination import SubmissionPagination
from .serializers import (
    AttributeSerializer,
    EndpointDetailSerializer,
    EndpointListSerializer,
    EndpointWriteSerializer,
    SubmissionSerializer,
)


class EndpointViewSet(viewsets.ModelViewSet):
    """CRUD for the current user's endpoints, plus API-key rotation."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return (
            Endpoint.objects.filter(owner=self.request.user)
            .annotate(
                submission_count=Count("submissions", distinct=True),
                attribute_count=Count("attributes", distinct=True),
            )
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        if self.action == "list":
            return EndpointListSerializer
        if self.action in ("create", "update", "partial_update"):
            return EndpointWriteSerializer
        return EndpointDetailSerializer

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def create(self, request, *args, **kwargs):
        write = EndpointWriteSerializer(data=request.data)
        write.is_valid(raise_exception=True)
        endpoint = write.save(owner=request.user)
        detail = EndpointDetailSerializer(endpoint, context=self.get_serializer_context())
        return Response(detail.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        write = EndpointWriteSerializer(instance, data=request.data, partial=partial)
        write.is_valid(raise_exception=True)
        write.save()
        detail = EndpointDetailSerializer(instance, context=self.get_serializer_context())
        return Response(detail.data)

    @action(detail=True, methods=["post"], url_path="rotate-key")
    def rotate_key(self, request, pk=None):
        endpoint = self.get_object()
        new_key = endpoint.rotate_api_key()
        return Response({"api_key": new_key}, status=status.HTTP_200_OK)


class _EndpointScopedMixin:
    """Resolve and ownership-check the parent endpoint from the URL."""

    permission_classes = [IsAuthenticated]

    def get_endpoint(self):
        return get_object_or_404(
            Endpoint, pk=self.kwargs["endpoint_pk"], owner=self.request.user
        )


class AttributeListCreateView(_EndpointScopedMixin, ListCreateAPIView):
    serializer_class = AttributeSerializer

    def get_queryset(self):
        return self.get_endpoint().attributes.all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["endpoint"] = self.get_endpoint()
        return ctx

    def perform_create(self, serializer):
        serializer.save(endpoint=self.get_endpoint())


class AttributeDetailView(_EndpointScopedMixin, RetrieveUpdateDestroyAPIView):
    serializer_class = AttributeSerializer

    def get_queryset(self):
        return self.get_endpoint().attributes.all()

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        ctx["endpoint"] = self.get_endpoint()
        return ctx


class SubmissionListView(_EndpointScopedMixin, APIView):
    """Paginated, searchable submissions for an endpoint."""

    pagination_class = SubmissionPagination

    def get(self, request, endpoint_pk=None):
        endpoint = self.get_endpoint()
        qs = endpoint.submissions.all()

        search = request.query_params.get("search", "").strip()
        if search:
            # Match any value (or key) inside the JSON payload, case-insensitive,
            # by casting the JSON column to text. Portable across SQLite/Postgres.
            qs = qs.annotate(
                _data_text=Cast("data", output_field=TextField())
            ).filter(_data_text__icontains=search)

        paginator = SubmissionPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = SubmissionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class SubmissionDetailView(_EndpointScopedMixin, APIView):
    def delete(self, request, endpoint_pk=None, pk=None):
        endpoint = self.get_endpoint()
        submission = get_object_or_404(endpoint.submissions, pk=pk)
        submission.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExportView(_EndpointScopedMixin, APIView):
    """Download all submissions as CSV or JSON.

    Columns = attribute keys (in defined order) + created_at.
    """

    def get(self, request, endpoint_pk=None):
        endpoint = self.get_endpoint()
        fmt = request.query_params.get("format", "csv").lower()
        attributes = list(endpoint.attributes.order_by("order", "id"))
        keys = [a.key for a in attributes]
        submissions = endpoint.submissions.order_by("-created_at")

        if fmt == "json":
            rows = []
            for sub in submissions:
                row = {key: sub.data.get(key) for key in keys}
                row["created_at"] = sub.created_at.isoformat()
                rows.append(row)
            response = JsonResponse(rows, safe=False, json_dumps_params={"indent": 2})
            response["Content-Disposition"] = (
                f'attachment; filename="{endpoint.slug}-submissions.json"'
            )
            return response

        if fmt == "csv":
            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = (
                f'attachment; filename="{endpoint.slug}-submissions.csv"'
            )
            writer = csv.writer(response)
            writer.writerow(keys + ["created_at"])
            for sub in submissions:
                row = [_csv_cell(sub.data.get(key)) for key in keys]
                row.append(sub.created_at.isoformat())
                writer.writerow(row)
            return response

        return Response(
            {"detail": "Unsupported format. Use format=csv or format=json."},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _csv_cell(value):
    """Render a JSON value into a flat CSV cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return value
