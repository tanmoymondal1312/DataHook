"""Public data-ingest endpoint.

`POST /ingest/{slug}/` is the shared URL developers embed in their sites/apps.
It is authenticated by the ``X-API-Key`` header (NOT JWT), accepts JSON, form-
urlencoded and multipart bodies, strictly validates against the endpoint's typed
attributes, stores a submission and (optionally) fires an FCM push.
"""

import logging

from rest_framework import status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .fcm import send_submission_notification
from .models import Endpoint, Submission
from .validators import TypeValidationError, coerce_value

logger = logging.getLogger("endpoints")


def _client_ip(request):
    """Best-effort client IP, honoring a single proxy hop via X-Forwarded-For."""
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def _is_empty(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == "":
        return True
    return False


class IngestView(APIView):
    """Public, API-key-authenticated submission intake."""

    permission_classes = [AllowAny]
    authentication_classes = []  # No session/JWT — key is in the header.
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ingest"

    def post(self, request, slug=None):
        # 1) Resolve endpoint by slug.
        try:
            endpoint = Endpoint.objects.get(slug=slug)
        except Endpoint.DoesNotExist:
            return Response(
                {"detail": "Endpoint not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # 2) Authenticate via X-API-Key header.
        api_key = request.headers.get("X-API-Key", "")
        if not api_key or not _constant_time_eq(api_key, endpoint.api_key):
            return Response(
                {"detail": "Invalid or missing API key."},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # 3) Extract the incoming payload (works for JSON and form bodies).
        incoming = request.data
        if not hasattr(incoming, "get"):
            return Response(
                {"detail": "Request body must be a JSON object or form data."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # 4) Validate strictly against the endpoint's attribute schema.
        attributes = list(endpoint.attributes.order_by("order", "id"))
        cleaned, errors = self._validate_payload(attributes, incoming)
        if errors:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

        # 5) Store the submission.
        submission = Submission.objects.create(
            endpoint=endpoint,
            data=cleaned,
            source_ip=_client_ip(request),
        )

        # 6) Fire push notification (best-effort, never blocks the 201).
        if endpoint.notify_on_submit:
            try:
                send_submission_notification(endpoint, submission)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Notification dispatch failed: %s", exc)

        return Response(
            {"success": True, "id": submission.id},
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _validate_payload(attributes, incoming):
        """Return (cleaned_dict, errors_dict) per the strict rules."""
        errors = {}
        cleaned = {}
        defined_keys = {attr.key for attr in attributes}

        # Reject any key not defined on the endpoint.
        for provided_key in incoming.keys():
            if provided_key not in defined_keys:
                errors[provided_key] = "Unknown field."

        for attr in attributes:
            present = attr.key in incoming
            raw = incoming.get(attr.key) if present else None

            if not present or _is_empty(raw):
                if attr.required:
                    errors[attr.key] = "This field is required."
                # Optional & absent/empty -> simply omit from stored data.
                continue

            try:
                cleaned[attr.key] = coerce_value(attr.type, raw)
            except TypeValidationError as exc:
                errors[attr.key] = exc.message

        return cleaned, errors


def _constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string comparison to avoid API-key timing leaks."""
    from hmac import compare_digest

    try:
        return compare_digest(str(a), str(b))
    except Exception:
        return False
