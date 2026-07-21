"""Firebase Cloud Messaging integration.

Initialization is lazy and defensive: if ``FIREBASE_CREDENTIALS`` is unset or the
Admin SDK cannot be initialized, push simply becomes a no-op so the rest of the
API keeps working (useful for local dev without a service-account file).
"""

import logging
import os

from django.conf import settings

logger = logging.getLogger("endpoints")

_initialized = False
_enabled = False


def _ensure_initialized():
    """Initialize the firebase-admin app once; cache success/failure state."""
    global _initialized, _enabled
    if _initialized:
        return _enabled

    _initialized = True
    cred_path = getattr(settings, "FIREBASE_CREDENTIALS", "")
    if not cred_path or not os.path.exists(cred_path):
        logger.info("FCM disabled: FIREBASE_CREDENTIALS not set or file missing.")
        _enabled = False
        return False

    try:
        import firebase_admin
        from firebase_admin import credentials

        if not firebase_admin._apps:
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        _enabled = True
        logger.info("FCM initialized.")
    except Exception as exc:  # pragma: no cover - depends on external SDK
        logger.warning("FCM initialization failed: %s", exc)
        _enabled = False

    return _enabled


def _short_summary(endpoint, data: dict) -> str:
    """Body text from the first two field values (in attribute order)."""
    keys = list(
        endpoint.attributes.order_by("order", "id").values_list("key", flat=True)
    )
    if not keys:
        keys = list(data.keys())
    parts = []
    for key in keys[:2]:
        if key in data and data[key] not in (None, ""):
            parts.append(f"{key}: {data[key]}")
    return " · ".join(parts) if parts else "New data received"


def send_submission_notification(endpoint, submission) -> dict:
    """Push a 'new submission' notification to all of the owner's devices.

    Returns a small report dict; prunes tokens FCM reports as unregistered.
    Never raises — failures are logged and swallowed so ingest still succeeds.
    """
    report = {"sent": 0, "failed": 0, "pruned": 0, "enabled": False}

    if not _ensure_initialized():
        return report
    report["enabled"] = True

    try:
        from firebase_admin import messaging
    except Exception as exc:  # pragma: no cover
        logger.warning("FCM messaging import failed: %s", exc)
        return report

    devices = list(endpoint.owner.devices.all())
    if not devices:
        return report

    title = f"New submission · {endpoint.name}"
    body = _short_summary(endpoint, submission.data)
    data_payload = {
        "endpoint_id": str(endpoint.id),
        "submission_id": str(submission.id),
        "type": "submission",
    }

    stale_tokens = []
    for device in devices:
        message = messaging.Message(
            token=device.fcm_token,
            notification=messaging.Notification(title=title, body=body),
            data=data_payload,
            android=messaging.AndroidConfig(priority="high"),
        )
        try:
            messaging.send(message)
            report["sent"] += 1
        except messaging.UnregisteredError:
            stale_tokens.append(device.fcm_token)
        except Exception as exc:  # pragma: no cover
            report["failed"] += 1
            logger.warning("FCM send failed for %s: %s", device.fcm_token[:12], exc)

    if stale_tokens:
        from accounts.models import Device

        deleted, _ = Device.objects.filter(fcm_token__in=stale_tokens).delete()
        report["pruned"] = deleted
        logger.info("Pruned %s unregistered FCM token(s).", deleted)

    return report
