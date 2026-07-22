"""Firebase Cloud Messaging integration.

Initialization is lazy and defensive: if ``FIREBASE_CREDENTIALS`` is unset or the
Admin SDK cannot be initialized, push simply becomes a no-op so the rest of the
API keeps working (useful for local dev without a service-account file).
"""

import json
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


# Notification bodies are truncated well before FCM's limit — the shade only
# shows a couple of lines anyway, and the full record travels in the data payload.
NOTIFICATION_BODY_MAX = 240

# The subtitle shares the one-line header with the app name and timestamp,
# so it has far less room than the body.
NOTIFICATION_SUBTITLE_MAX = 40

GENERIC_BODY = "New submission received"


def _display_value(value) -> str:
    """Render a submitted value the way a human would read it in a notification."""
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def build_notification(endpoint, submission) -> dict:
    """Everything the client needs to render the notification for ``submission``.

    Returns ``{title, body, subtitle, image_url, logo_url}``:

    - **title** — ``notify_title`` when set, else ``New submission · <name>``.
    - **body** — values of the attributes flagged ``show_in_notification``, in
      attribute order, as ``Label: value`` joined by ``·``. Omitted/empty fields
      are skipped; falls back to the generic line so the body is never blank.
    - **subtitle** — the raw value of the ``show_as_subtitle`` attribute (no
      label prefix; it renders in the cramped header line). ``""`` if unset.
    - **image_url** — the URL from an ``image`` attribute that is flagged
      ``show_in_notification``, shown as the big picture. ``""`` if none.
    - **logo_url** — the endpoint's uploaded logo, shown as the large icon.

    Image attributes never contribute to the body — a raw URL reads as noise.
    """
    data = submission.data if isinstance(submission.data, dict) else {}
    # One pass over the prefetched attributes; they arrive in (order, id).
    attributes = sorted(endpoint.attributes.all(), key=lambda a: (a.order, a.id))

    def value_of(attribute) -> str:
        raw = data.get(attribute.key)
        if raw is None:
            return ""
        return _display_value(raw).strip()

    parts = []
    subtitle = ""
    image_url = ""

    for attribute in attributes:
        text = value_of(attribute)
        is_image = attribute.type == "image"

        if attribute.show_as_subtitle and text and not subtitle:
            subtitle = text
        if is_image and attribute.show_in_notification and text and not image_url:
            image_url = text
        if attribute.show_in_notification and text and not is_image:
            parts.append(f"{attribute.label}: {text}")

    body = " · ".join(parts) if parts else GENERIC_BODY
    if len(body) > NOTIFICATION_BODY_MAX:
        body = body[: NOTIFICATION_BODY_MAX - 1].rstrip() + "…"

    if len(subtitle) > NOTIFICATION_SUBTITLE_MAX:
        subtitle = subtitle[: NOTIFICATION_SUBTITLE_MAX - 1].rstrip() + "…"

    return {
        "title": (endpoint.notify_title or "").strip()
        or f"New submission · {endpoint.name}",
        "body": body,
        "subtitle": subtitle,
        "image_url": image_url,
        "logo_url": endpoint.notify_logo_url,
    }


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

    content = build_notification(endpoint, submission)
    # Data values must be strings for FCM. `submission_json` embeds the whole
    # submission so tapping the notification opens it with no extra fetch.
    # (FCM caps the total data payload at ~4KB; very large submissions may
    # exceed it — see the InvalidArgumentError handling below.)
    submission_json = json.dumps(
        {
            "id": submission.id,
            "data": submission.data,
            "created_at": submission.created_at.isoformat(),
        }
    )
    data_payload = {
        "type": "submission",
        "endpoint_id": str(endpoint.id),
        "endpoint_name": endpoint.name,
        "submission_id": str(submission.id),
        "submission_json": submission_json,
        # The app builds the notification itself from these (see below).
        "title": content["title"],
        "body": content["body"],
        "subtitle": content["subtitle"],
        "image_url": content["image_url"],
        "logo_url": content["logo_url"],
    }

    stale_tokens = []
    for device in devices:
        # Deliberately **data-only** (no `notification` block). With a
        # notification block the system builds the tray notification itself
        # whenever the app is backgrounded, which silently drops the subtitle
        # and the logo. Data-only means our own handler always runs and the
        # notification looks the same foreground or background; `priority=high`
        # keeps delivery prompt.
        message = messaging.Message(
            token=device.fcm_token,
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
        except fb_exceptions.InvalidArgumentError as exc:
            # INVALID_ARGUMENT can mean a bad token OR a bad/oversized payload.
            # Only prune when the error is clearly about the registration token,
            # so a too-large submission_json can't wrongly delete valid tokens.
            msg = str(exc).lower()
            if "registration token" in msg or "not a valid fcm" in msg:
                stale_tokens.append(device.fcm_token)
            else:
                report["failed"] += 1
                logger.warning(
                    "FCM InvalidArgument (payload, not token) for %s: %s",
                    device.fcm_token[:12],
                    exc,
                )
        except Exception as exc:  # pragma: no cover
            report["failed"] += 1
            logger.warning("FCM send failed for %s: %s", device.fcm_token[:12], exc)

    if stale_tokens:
        from accounts.models import Device

        deleted, _ = Device.objects.filter(fcm_token__in=stale_tokens).delete()
        report["pruned"] = deleted
        logger.info("Pruned %s invalid/unregistered FCM token(s).", deleted)

    return report
