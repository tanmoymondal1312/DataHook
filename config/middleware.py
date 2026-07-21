"""Project middleware.

``IngestCorsMiddleware`` makes the public ``/ingest/{slug}/`` endpoint reachable
cross-origin from ANY site — django-cors-headers is scoped to ``/api/`` only (see
``CORS_URLS_REGEX``), so this handles the public path independently. Ingest is
authorized by the ``X-API-Key`` header (not cookies), so allowing all origins is
safe, and it lets browser ``fetch()`` calls and HTML forms from any site post.
"""

from django.http import HttpResponse

INGEST_PREFIX = "/ingest/"


class IngestCorsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_ingest = request.path.startswith(INGEST_PREFIX)

        # Short-circuit CORS preflight for ingest (the view only allows POST).
        if is_ingest and request.method == "OPTIONS":
            response = HttpResponse(status=204)
        else:
            response = self.get_response(request)

        if is_ingest:
            response["Access-Control-Allow-Origin"] = "*"
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
            response["Access-Control-Max-Age"] = "86400"

        return response
