"""Public app-update configuration endpoint.

`GET /api/app-update/` is deliberately unauthenticated: the Android app polls
it at cold start, before any login exists. It only ever returns the small,
public update configuration — no user data, no secrets.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AppUpdateConfig
from .serializers import AppUpdateConfigSerializer


class AppUpdateView(APIView):
    """Serve the single live update configuration to clients."""

    permission_classes = [AllowAny]
    authentication_classes = []  # No session/JWT — this is public.

    def get(self, request):
        config = AppUpdateConfig.load()
        return Response(AppUpdateConfigSerializer(config).data)