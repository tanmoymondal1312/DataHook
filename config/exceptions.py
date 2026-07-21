"""Consistent JSON error envelope for the DataHook API.

Wraps DRF's default handler so every error response has a predictable shape:

    {"detail": "...", "errors": {...}}

`detail` is a human-readable message; `errors` (when present) is a field->message
map. This keeps the Android client's parsing simple and uniform across 400/401/
403/404/405/429/500.
"""

from rest_framework.views import exception_handler


def custom_exception_handler(exc, context):
    # DRF always calls the handler as handler(exc, context).
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    envelope = {}

    if isinstance(data, dict):
        # Pull a top-level message out of common DRF keys.
        detail = data.get("detail")
        if detail is not None:
            envelope["detail"] = str(detail)
            # Field-level errors alongside a detail message (rare) are preserved.
            field_errors = {k: v for k, v in data.items() if k != "detail"}
            if field_errors:
                envelope["errors"] = field_errors
        else:
            # Field validation errors: {field: [messages]}
            envelope["detail"] = "Validation failed."
            envelope["errors"] = data
    elif isinstance(data, list):
        envelope["detail"] = "; ".join(str(item) for item in data)
    else:
        envelope["detail"] = str(data)

    response.data = envelope
    return response
