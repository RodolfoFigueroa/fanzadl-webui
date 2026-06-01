from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from fanzadl_webui.state import AppState

logger = logging.getLogger(__name__)

_KNOWN_EVENTS = frozenset(
    [
        "job_created",
        "job_completed",
        "job_failed",
        "job_cancelled",
        "item_added",
        "item_expired",
        "test",
    ]
)


async def fire_webhook(
    app_state: AppState,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """POST a signed JSON webhook envelope to the configured URL.

    Returns immediately without raising if the URL is not configured, the event
    type is filtered out, or delivery fails. All failures are logged as warnings.

    Args:
        app_state: Application state providing the webhook URL, secret, event
            filter, and shared HTTP client.
        event_type: Event identifier such as ``"job_completed"`` or ``"test"``.
        data: Arbitrary event payload to include in the ``"data"`` field of the
            envelope.
    """
    url = app_state.webhook_url
    if url is None:
        return
    if event_type != "test" and event_type not in app_state.webhook_events:
        return

    envelope = {
        "event": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
        "data": data,
    }
    body = json.dumps(envelope, default=str).encode()

    headers: dict[str, str] = {"Content-Type": "application/json"}
    secret = app_state.webhook_secret
    if secret:
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Webhook-Signature"] = f"sha256={sig}"

    try:
        response = await app_state.http_client.post(
            url,
            content=body,
            headers=headers,
            timeout=httpx.Timeout(5.0),
        )
        if not response.is_success:
            logger.warning(
                "Webhook delivery failed: %s returned HTTP %s",
                url,
                response.status_code,
            )
    except Exception:
        logger.warning("Webhook delivery error for %s", url, exc_info=True)
