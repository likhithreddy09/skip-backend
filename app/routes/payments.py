"""UPI payment orders and SIP mandates — https://developers.oropocket.com/docs/payments/
Needs the OroPocket `payments` capability."""

import secrets

from flask import Blueprint
from pymongo import DESCENDING, ReturnDocument

from ..db import get_db
from ..errors import ApiError, ok
from ..extensions import limiter
from ..schemas import PaymentOrderIn, SipCreateIn
from ..security import current_user, require_auth
from ..services import oropocket
from ..services.gold_accounts import ensure_api_user_code
from ..utils import query_int, parse_body, utcnow

bp = Blueprint("payments", __name__, url_prefix="/payments")

PUBLIC_FIELDS = {"_id": 0, "user_id": 0, "user_code": 0}


def _gate():
    oropocket.require_capability(
        lambda c: c["payments_enabled"],
        "The `payments` capability isn't enabled for this OroPocket key. "
        "Use /gold/embed-session with screen buy or sip instead.",
    )


def _reference(prefix: str, given: str | None) -> str:
    return given or f"{prefix}_{secrets.token_hex(10)}"


# --- one-off UPI orders ------------------------------------------------------------


@bp.post("/orders")
@require_auth
@limiter.limit("20 per minute")
def create_order():
    _gate()
    body = parse_body(PaymentOrderIn)
    user = current_user()
    db = get_db()
    reference = _reference("ord", body.reference)

    existing = db.payment_orders.find_one({"reference": reference})
    if existing:
        if existing["user_id"] != user["_id"]:
            raise ApiError(409, "REFERENCE_IN_USE", "Use a different reference.")
        return ok({k: v for k, v in existing.items() if k not in PUBLIC_FIELDS})

    payload = {
        "user_code": ensure_api_user_code(user),
        "amount_inr": body.amount_inr,
        "asset_type": body.asset_type,
        "checkout_type": body.checkout_type,
        "reference": reference,
        **({"return_url": body.return_url} if body.return_url else {}),
    }
    data = oropocket.call(
        "POST", "/payments/orders", json=payload, idempotency_key=f"order-{reference}"
    ).raise_for_error().data

    now = utcnow()
    doc = {
        "payment_id": data["payment_id"],
        "reference": reference,
        "user_id": user["_id"],
        "user_code": payload["user_code"],
        "amount_inr": body.amount_inr,
        "asset_type": body.asset_type,
        "checkout_type": body.checkout_type,
        "status": data.get("status", "created"),
        "checkout_url": data.get("checkout_url"),
        "upi": data.get("upi"),
        "expires_at": data.get("expires_at"),
        "created_at": now,
        "updated_at": now,
    }
    db.payment_orders.update_one({"payment_id": doc["payment_id"]}, {"$setOnInsert": doc}, upsert=True)
    return ok({k: v for k, v in doc.items() if k not in PUBLIC_FIELDS}, status=201)


@bp.get("/orders")
@require_auth
def list_orders():
    limit = query_int("limit", 50, 1, 200)
    docs = get_db().payment_orders.find({"user_id": current_user()["_id"]}, PUBLIC_FIELDS)
    return ok(list(docs.sort("created_at", DESCENDING).limit(limit)))


@bp.get("/orders/<payment_id>")
@require_auth
def get_order(payment_id: str):
    """Fallback when a webhook was missed: refresh the status from OroPocket."""
    db = get_db()
    order = db.payment_orders.find_one({"payment_id": payment_id, "user_id": current_user()["_id"]})
    if not order:
        raise ApiError(404, "NOT_FOUND", "Payment not found.")
    if order["status"] in ("created", "paid", "refund_due"):
        res = oropocket.call("GET", f"/payments/orders/{payment_id}")
        if res.ok and res.data:
            order = db.payment_orders.find_one_and_update(
                {"_id": order["_id"]},
                {"$set": {"status": res.data.get("status", order["status"]), "updated_at": utcnow()}},
                return_document=ReturnDocument.AFTER,
            )
    return ok({k: v for k, v in order.items() if k not in PUBLIC_FIELDS})


# --- SIP mandates ------------------------------------------------------------------


@bp.post("/sips")
@require_auth
@limiter.limit("10 per minute")
def create_sip():
    _gate()
    body = parse_body(SipCreateIn)
    user = current_user()
    db = get_db()
    reference = _reference("sip", body.reference)

    existing = db.oro_sips.find_one({"reference": reference})
    if existing:
        if existing.get("user_id") != user["_id"]:
            raise ApiError(409, "REFERENCE_IN_USE", "Use a different reference.")
        return ok({k: v for k, v in existing.items() if k not in PUBLIC_FIELDS})

    payload = {
        "user_code": ensure_api_user_code(user),
        "installment_amount_inr": body.installment_amount_inr,
        "frequency": body.frequency,
        "asset_type": body.asset_type,
        "reference": reference,
        **({"name": body.name} if body.name else {}),
        **({"return_url": body.return_url} if body.return_url else {}),
    }
    data = oropocket.call(
        "POST", "/payments/sips", json=payload, idempotency_key=f"sip-{reference}"
    ).raise_for_error().data

    now = utcnow()
    doc = {
        "sip_id": data["sip_id"],
        "reference": reference,
        "user_id": user["_id"],
        "user_code": payload["user_code"],
        "name": body.name,
        "installment_amount_inr": body.installment_amount_inr,
        "frequency": body.frequency,
        "asset_type": body.asset_type,
        "status": data.get("status", "pending_authorisation"),
        "checkout_url": data.get("checkout_url"),
        "authorise_by": data.get("authorise_by"),
        "installments_completed": 0,
        "created_at": now,
        "updated_at": now,
    }
    db.oro_sips.update_one({"sip_id": doc["sip_id"]}, {"$setOnInsert": doc}, upsert=True)
    return ok({k: v for k, v in doc.items() if k not in PUBLIC_FIELDS}, status=201)


@bp.get("/sips")
@require_auth
def list_sips():
    docs = get_db().oro_sips.find({"user_id": current_user()["_id"]}, PUBLIC_FIELDS)
    return ok(list(docs.sort("created_at", DESCENDING)))


def _owned_sip(sip_id: str) -> dict:
    sip = get_db().oro_sips.find_one({"sip_id": sip_id, "user_id": current_user()["_id"]})
    if not sip:
        raise ApiError(404, "NOT_FOUND", "SIP not found.")
    return sip


@bp.get("/sips/<sip_id>")
@require_auth
def get_sip(sip_id: str):
    sip = _owned_sip(sip_id)
    res = oropocket.call("GET", f"/payments/sips/{sip_id}")
    if res.ok and res.data:
        updates = {k: res.data[k] for k in ("status", "next_installment_at", "installments_completed") if k in res.data}
        sip = get_db().oro_sips.find_one_and_update(
            {"_id": sip["_id"]},
            {"$set": {**updates, "updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
    return ok({k: v for k, v in sip.items() if k not in PUBLIC_FIELDS})


@bp.post("/sips/<sip_id>/cancel")
@require_auth
def cancel_sip(sip_id: str):
    _gate()
    sip = _owned_sip(sip_id)
    data = oropocket.call(
        "POST", f"/payments/sips/{sip_id}/cancel", idempotency_key=f"sip-cancel-{sip_id}"
    ).raise_for_error().data or {}
    sip = get_db().oro_sips.find_one_and_update(
        {"_id": sip["_id"]},
        {"$set": {"status": data.get("status", "cancelled"), "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return ok({k: v for k, v in sip.items() if k not in PUBLIC_FIELDS})
