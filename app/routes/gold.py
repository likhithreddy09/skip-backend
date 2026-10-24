from datetime import timedelta

from flask import Blueprint, current_app, request
from pymongo import DESCENDING

from ..db import get_db
from ..errors import ApiError, ok
from ..extensions import limiter
from ..schemas import EmbedSessionIn, TradeConfirmIn, TradeQuoteIn
from ..security import current_user, require_auth
from ..services import oropocket
from ..services.gold_accounts import (
    ensure_api_user_code,
    get_account,
    read_holding,
    record_transaction,
    remember_user_code,
    user_codes_for,
)
from ..utils import parse_body, query_int, utcnow

bp = Blueprint("gold", __name__, url_prefix="/gold")


def _mode():
    return current_app.config["OROPOCKET_MODE"]


# --- public ------------------------------------------------------------------------


@bp.get("/prices")
def prices():
    data, cached, stale = oropocket.get_prices()
    return ok({"prices": data, "mode": _mode(), "cached": cached, "stale": stale})


@bp.get("/prices/history")
def price_history():
    params = {k: request.args[k] for k in ("asset", "period") if request.args.get(k)}
    res = oropocket.call("GET", "/prices/history", params=params).raise_for_error()
    return ok(res.data)


# --- account -----------------------------------------------------------------------


@bp.get("/capabilities")
@require_auth
def capabilities():
    return ok(oropocket.get_capabilities())


@bp.post("/embed-session")
@require_auth
@limiter.limit("20 per minute")
def embed_session():
    """Mints a single-use Hosted Embed URL for the signed-in user (10-minute TTL)."""
    body = parse_body(EmbedSessionIn)
    user = current_user()
    mobile = user.get("mobile")
    if not mobile:
        raise ApiError(
            422,
            "MOBILE_REQUIRED",
            "Add your mobile number in your profile before buying or selling gold.",
        )
    payload = {
        "flow": "embed",
        "mobile": mobile,
        "meta": {"app": "SkipMint", "source": body.source or "app", "skipmint_user_id": str(user["_id"])},
    }
    name = user.get("name") or (user.get("profile") or {}).get("name")
    if name:
        payload["name"] = name[:128]
    if user.get("email"):
        payload["email"] = user["email"]
    if body.launch:
        payload["launch"] = body.launch.model_dump(exclude_none=True)

    data = oropocket.init_embed(payload)
    remember_user_code(user["_id"], data["user_code"], "embed")
    return ok(
        {
            "embed_url": data["embed_url"],
            "expires_at": data.get("expires_at"),
            "expires_in_seconds": data.get("expires_in_seconds"),
            "user_existed": data.get("user_existed"),
            "launch_fallback": bool(data.get("launch_fallback")),
            "launch_error": data.get("launch_error"),
            "mode": data.get("mode") or _mode(),
        }
    )


@bp.get("/account")
@require_auth
def account():
    acc = get_account(current_user()["_id"]) or {}
    return ok(
        {
            "linked": bool(acc),
            "kyc_status": acc.get("kyc_status"),
            "kyc_reason": acc.get("kyc_reason"),
            "has_api_account": bool(acc.get("api_user_code")),
            "mode": acc.get("mode") or _mode(),
            "linked_at": acc.get("created_at"),
        }
    )


@bp.get("/portfolio")
@require_auth
def portfolio():
    for code in user_codes_for(current_user()["_id"]):
        res = oropocket.call("GET", f"/users/{code}/portfolio")
        if res.ok:
            raw = res.data or {}
            return ok(
                {
                    "synced": True,
                    "gold": read_holding(raw, "gold"),
                    "silver": read_holding(raw, "silver"),
                    "raw": raw,
                    "fetched_at": utcnow(),
                }
            )
    return ok({"synced": False, "gold": None, "silver": None, "raw": None, "fetched_at": utcnow()})


@bp.get("/transactions")
@require_auth
def transactions():
    """Webhook-recorded history, refreshed from OroPocket when reachable."""
    user = current_user()
    limit = query_int("limit", 50, 1, 200)
    if request.args.get("refresh", "true") != "false":
        for code in user_codes_for(user["_id"]):
            res = oropocket.call("GET", f"/users/{code}/transactions", params={"limit": limit})
            if res.ok:
                for raw in (res.data or {}).get("transactions") or []:
                    record_transaction({**raw, "user_code": code}, user_id=user["_id"], source="api_sync")
                break

    docs = (
        get_db()
        .oro_transactions.find({"user_id": user["_id"]}, {"_id": 0, "user_id": 0})
        .sort("occurred_at", DESCENDING)
        .limit(limit)
    )
    return ok(list(docs))


@bp.get("/transactions/<transaction_id>/invoice")
@require_auth
def invoice(transaction_id: str):
    owned = get_db().oro_transactions.find_one(
        {"transaction_id": transaction_id, "user_id": current_user()["_id"]}
    )
    if not owned:
        raise ApiError(404, "NOT_FOUND", "Transaction not found.")
    res = oropocket.call("GET", f"/transactions/{transaction_id}/invoice").raise_for_error()
    return ok(res.data)


# --- raw-API trading (quote → confirm) ---------------------------------------------


def _trade_gate(side: str):
    if side not in ("buy", "sell"):
        raise ApiError(404, "NOT_FOUND", "Use /gold/trades/buy or /gold/trades/sell.")
    oropocket.require_capability(
        lambda c: c["raw_trading_enabled"]
        and side in c["allowed_apis"]
        and (side == "sell" or c["float_available_inr"] > 0),
        "Direct trading is off (needs ENABLE_RAW_TRADING, the capability, and a funded float). "
        "Use /gold/embed-session instead.",
    )


@bp.post("/trades/<side>/quote")
@require_auth
@limiter.limit("30 per minute")
def trade_quote(side: str):
    _trade_gate(side)
    body = parse_body(TradeQuoteIn)
    if side == "buy" and body.amount_inr is None:
        raise ApiError(422, "INVALID_AMOUNT", "Buys are quoted in amount_inr.")
    user = current_user()
    user_code = ensure_api_user_code(user)
    payload = {"user_code": user_code, "asset_type": body.asset_type}
    payload.update({"quantity_grams": body.quantity_grams} if body.quantity_grams else {"amount_inr": body.amount_inr})

    quote = oropocket.call("POST", f"/{side}/quote", json=payload).raise_for_error().data
    get_db().trade_quotes.insert_one(
        {
            "quote_id": quote["quote_id"],
            "user_id": user["_id"],
            "side": side,
            "asset_type": body.asset_type,
            "created_at": utcnow(),
            "purge_at": utcnow() + timedelta(hours=1),
        }
    )
    return ok(quote, status=201)


@bp.post("/trades/<side>/confirm")
@require_auth
@limiter.limit("30 per minute")
def trade_confirm(side: str):
    _trade_gate(side)
    body = parse_body(TradeConfirmIn)
    user = current_user()
    quote = get_db().trade_quotes.find_one(
        {"quote_id": body.quote_id, "user_id": user["_id"], "side": side}
    )
    if not quote:
        raise ApiError(404, "QUOTE_NOT_FOUND", "Quote not found or expired.")

    res = oropocket.call(
        "POST",
        f"/{side}/confirm",
        json={"quote_id": body.quote_id},
        idempotency_key=f"{side}-confirm-{body.quote_id}",
    ).raise_for_error()
    data = res.data or {}
    record_transaction(
        {**data, "asset_type": data.get("asset_type") or quote["asset_type"]},
        user_id=user["_id"],
        source="api",
        kind=side,
    )
    return ok(data)
