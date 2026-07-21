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


def send_submission_notification(endpoint, submission) -> dict:
    """Push a 'new submission' notification to all of the owner's devices.

    Sent via ``messaging.send()`` (FCM HTTP v1) per device token. The data
    payload carries the endpoint id/name and a short body so the Android client
    can render/route the notification itself. Tokens that FCM reports as
    invalid or unregistered are pruned from the DB.

    Returns a small report dict. Never raises — failures are logged and
    swallowed so the ingest request still succeeds.
    """
    report = {"sent": 0, "failed": 0, "pruned": 0, "enabled": False}

    if not _ensure_initialized():
        return report
    report["enabled"] = True

    try:
        from firebase_admin import exceptions as fb_exceptions
        from firebase_admin import messaging
    except Exception as exc:  # pragma: no cover
        logger.warning("FCM messaging import failed: %s", exc)
        return report

    devices = list(endpoint.owner.devices.all())
    if not devices:
        return report

    body_text = "New submission received"
    # Data values must be strings for FCM. These three keys are the documented
    # contract; submission_id/type are additive extras for the client to route
    # to / open the specific submission.
    data_payload = {
        "endpoint_id": str(endpoint.id),
        "endpoint_name": endpoint.name,
        "body": body_text,
        "submission_id": str(submission.id),
        "type": "submission",
    }

    stale_tokens = []
    for device in devices:
        message = messaging.Message(
            token=device.fcm_token,
            notification=messaging.Notification(
                title=f"New submission · {endpoint.name}", body=body_text
            ),
            data=data_payload,
            android=messaging.AndroidConfig(priority="high"),
        )
        try:
            messaging.send(message)
            report["sent"] += 1
        except messaging.UnregisteredError:
            # Token was valid but the app/token is no longer registered.
            stale_tokens.append(device.fcm_token)
        except messaging.SenderIdMismatchError:
            # Token belongs to a different Firebase sender — unusable here.
            stale_tokens.append(device.fcm_token)
        except fb_exceptions.InvalidArgumentError:
            # The message payload is fixed and valid, so an INVALID_ARGUMENT
            # here means the registration token itself is malformed/invalid.
            stale_tokens.append(device.fcm_token)
        except Exception as exc:  # pragma: no cover
            report["failed"] += 1
            logger.warning("FCM send failed for %s: %s", device.fcm_token[:12], exc)

    if stale_tokens:
        from accounts.models import Device

        deleted, _ = Device.objects.filter(fcm_token__in=stale_tokens).delete()
        report["pruned"] = deleted
        logger.info("Pruned %s invalid/unregistered FCM token(s).", deleted)

    return report
