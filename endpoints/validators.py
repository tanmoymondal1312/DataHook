"""Reusable validators for attribute keys and typed submission values."""

import re
from datetime import date

from django.core.exceptions import ValidationError

# A valid attribute key: lowercase letters, digits and underscores only.
# Must start with a letter or underscore (never a digit) so it is a safe
# identifier for JSON payloads, CSV headers and HTML input names.
KEY_REGEX = re.compile(r"^[a-z_][a-z0-9_]*$")

# Permissive phone matcher: digits, spaces, +, -, parentheses.
PHONE_REGEX = re.compile(r"^[+]?[\d\s\-()]{3,}$")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

BOOL_TRUE = {"true", "1", "yes", "on"}
BOOL_FALSE = {"false", "0", "no", "off"}


def validate_attribute_key(value: str):
    """Django model validator: enforce the strict no-space slug rule."""
    if not KEY_REGEX.match(value or ""):
        raise ValidationError(
            "Key must be lowercase letters, digits and underscores only "
            "(no spaces), starting with a letter or underscore.",
            code="invalid_key",
        )


class TypeValidationError(Exception):
    """Raised by ``coerce_value`` when a value fails its type check."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _is_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        float(str(value).strip())
        return True
    except (TypeError, ValueError):
        return False


def coerce_value(attr_type: str, raw):
    """Validate ``raw`` for ``attr_type`` and return a normalized value.

    Raises ``TypeValidationError`` with a human-readable message on failure.
    Accepts both native JSON types and strings (form-encoded submissions arrive
    as strings), so the same logic serves JSON and HTML-form ingests.
    """
    # Treat None / empty string as "missing" — required-ness is checked by the
    # caller before this runs, so anything reaching here for an optional field
    # that is empty is simply passed through as-is.
    if raw is None:
        return None

    if attr_type == "text":
        if isinstance(raw, (dict, list)):
            raise TypeValidationError("Expected a text value.")
        return str(raw)

    if attr_type == "email":
        s = str(raw).strip()
        if not EMAIL_REGEX.match(s):
            raise TypeValidationError("Must be a valid email address.")
        return s

    if attr_type == "phone":
        s = str(raw).strip()
        if not PHONE_REGEX.match(s):
            raise TypeValidationError(
                "Must be a valid phone number (digits, +, -, spaces)."
            )
        return s

    if attr_type == "number":
        if not _is_number(raw):
            raise TypeValidationError("Must be a number.")
        num = float(str(raw).strip()) if not isinstance(raw, (int, float)) else raw
        # Preserve integers as ints for cleaner storage/exports.
        if isinstance(num, float) and num.is_integer():
            return int(num)
        return num

    if attr_type == "date":
        s = str(raw).strip()
        try:
            date.fromisoformat(s)
        except (ValueError, TypeError):
            raise TypeValidationError("Must be an ISO date (YYYY-MM-DD).")
        return s

    if attr_type == "boolean":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in BOOL_TRUE:
            return True
        if s in BOOL_FALSE:
            return False
        raise TypeValidationError("Must be a boolean (true/false/1/0).")

    # Unknown type — should never happen given the model's choices.
    raise TypeValidationError(f"Unknown attribute type '{attr_type}'.")
