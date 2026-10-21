import json

from flask import Blueprint, current_app, request
from pymongo.errors import DuplicateKeyError

from ..db import get_db
from ..errors import ApiError, ok
from ..extensions import limiter
from ..services.webhooks import process_stored_event, verify_signature
from ..utils import utcnow

bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


@bp.post("/oropocket")
@limiter.exempt
def oropocket_webhook():
    secret = current_app.config["OROPOCKET_WEBHOOK_SECRET"]
    if not secret:
        # Non-2xx so OroPocket keeps retrying until the secret is configured.
        raise ApiError(503, "WEBHOOK_NOT_CONFIGURED", "OROPOCKET_WEBHOOK_SECRET is not set.")

    raw = request.get_data(cache=False)
    if not verify_signature(
        secret,
        raw,
        request.headers.get("X-OroPocket-Signature", ""),
        request.headers.get("X-OroPocket-Timestamp", ""),
    ):
        raise ApiError(401, "INVALID_SIGNATURE", "Signature or timestamp check failed.")

    try:
        event = json.loads(raw)
    except ValueError:
        raise ApiError(400, "INVALID_JSON", "Body is not JSON.")

    event_id = str(event.get("event_id") or request.headers.get("X-OroPocket-Event-Id") or "")
    if not event_id:
        raise ApiError(400, "MISSING_EVENT_ID", "event_id is required.")

    try:
        get_db().webhook_events.insert_one(
            {
                "event_id": event_id,
                "event": str(event.get("event") or request.headers.get("X-OroPocket-Event") or "unknown"),
                "mode": event.get("mode") or (event.get("data") or {}).get("mode"),
                "created_at": event.get("created_at"),
                "received_at": utcnow(),
                "data": event.get("data") or {},
                "processed_at": None,
                "error": None,
            }
        )
    except DuplicateKeyError:
        return ok({"received": True, "duplicate": True})

    # Projection is quick DB work; failures are kept on the event for replay.
    process_stored_event(event_id)
    return ok({"received": True})
