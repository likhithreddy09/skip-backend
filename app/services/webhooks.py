"""OroPocket webhooks: https://developers.oropocket.com/docs/webhooks/"""

import hashlib
import hmac
import logging
import time

from ..db import get_db
from ..utils import utcnow
from .gold_accounts import record_transaction, user_id_for_code

log = logging.getLogger(__name__)
MAX_AGE_SECONDS = 300


def verify_signature(secret: str, raw_body: bytes, signature: str, timestamp: str) -> bool:
    """Signed over f"{timestamp}.{raw_body}", not the body alone."""
    try:
        age = abs(time.time() - int(timestamp))
    except (TypeError, ValueError):
        return False
    if age > MAX_AGE_SECONDS:
        return False
    expected = "sha256=" + hmac.new(
        secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature or "")


SIP_STATUS_BY_EVENT = {
    "sip.created": "pending_authorisation",
    "sip.activated": "active",
    "sip.mandate_failed": "failed",
}
PAYMENT_STATUS_BY_EVENT = {
    "payment.completed": "completed",
    "payment.failed": "failed",
    "payment.expired": "expired",
    "payment.refunded": "refunded",
}
KYC_STATUS_BY_EVENT = {
    "kyc.approved": "approved",
    "kyc.under_review": "under_review",
    "kyc.rejected": "rejected",
}


def apply_event(event: dict) -> None:
    """Project a stored event onto the domain collections. Must be idempotent."""
    db = get_db()
    name = event["event"]
    data = event.get("data") or {}
    user_id = user_id_for_code(data.get("user_code"))
    now = utcnow()

    if name in ("buy.completed", "sell.completed"):
        record_transaction(data, user_id=user_id, source="webhook", kind=name.split(".")[0])

    elif name.startswith("sip."):
        sip_id = data.get("sip_id") or data.get("id")
        if sip_id:
            update = {"updated_at": now, "last_event": name}
            if name in SIP_STATUS_BY_EVENT:
                update["status"] = data.get("status") or SIP_STATUS_BY_EVENT[name]
            if user_id:
                update["user_id"] = user_id
            for key in ("installment_amount_inr", "frequency", "asset_type", "next_installment_at"):
                if data.get(key) is not None:
                    update[key] = data[key]
            inc = {"installments_completed": 1} if name == "sip.installment" else {}
            db.oro_sips.update_one(
                {"sip_id": str(sip_id)},
                {"$set": update, "$setOnInsert": {"sip_id": str(sip_id), "created_at": now},
                 **({"$inc": inc} if inc else {})},
                upsert=True,
            )
        if name == "sip.installment":
            record_transaction(data, user_id=user_id, source="webhook", kind="sip_installment")

    elif name.startswith("payment."):
        payment_id = data.get("payment_id") or data.get("id")
        if payment_id:
            update = {"status": data.get("status") or PAYMENT_STATUS_BY_EVENT.get(name), "updated_at": now}
            if data.get("refund"):
                update["refund"] = data["refund"]
            db.payment_orders.update_one({"payment_id": str(payment_id)}, {"$set": update})
        if name == "payment.completed":
            record_transaction(data, user_id=user_id, source="webhook", kind="buy")

    elif name in KYC_STATUS_BY_EVENT and user_id:
        db.oro_accounts.update_one(
            {"user_id": user_id},
            {"$set": {"kyc_status": KYC_STATUS_BY_EVENT[name], "kyc_reason": data.get("reason"), "updated_at": now}},
        )


def process_stored_event(event_id: str) -> None:
    db = get_db()
    event = db.webhook_events.find_one({"event_id": event_id})
    if not event or event.get("processed_at"):
        return
    try:
        apply_event(event)
        db.webhook_events.update_one(
            {"_id": event["_id"]}, {"$set": {"processed_at": utcnow(), "error": None}}
        )
    except Exception as e:  # stored already; can be replayed later
        log.exception("Webhook %s failed to apply", event_id)
        db.webhook_events.update_one({"_id": event["_id"]}, {"$set": {"error": str(e)[:500]}})
