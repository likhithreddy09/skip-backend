"""Links SkipMint users to OroPocket user_codes and records gold activity."""

from datetime import datetime

from bson import ObjectId
from flask import current_app
from pymongo import ReturnDocument

from ..db import get_db
from ..utils import as_utc, utcnow
from . import oropocket


def get_account(user_id: ObjectId) -> dict | None:
    return get_db().oro_accounts.find_one({"user_id": user_id})


def remember_user_code(user_id: ObjectId, user_code: str, kind: str) -> None:
    now = utcnow()
    update = {
        "$addToSet": {"user_codes": user_code},
        "$set": {"updated_at": now, "mode": current_app.config["OROPOCKET_MODE"]},
        "$setOnInsert": {"user_id": user_id, "created_at": now},
    }
    update["$set"]["api_user_code" if kind == "api" else "last_embed_user_code"] = user_code
    get_db().oro_accounts.update_one({"user_id": user_id}, update, upsert=True)


def ensure_api_user_code(user: dict) -> str:
    """Persistent handle for raw-API trades and payments (embed codes are single-use)."""
    account = get_account(user["_id"])
    if account and account.get("api_user_code"):
        return account["api_user_code"]
    payload = {"flow": "api", "mobile": user["mobile"]}
    name = user.get("name") or (user.get("profile") or {}).get("name")
    if name:
        payload["name"] = name[:128]
    data = oropocket.call("POST", "/users/init", json=payload).raise_for_error().data
    remember_user_code(user["_id"], data["user_code"], "api")
    return data["user_code"]


def user_codes_for(user_id: ObjectId) -> list[str]:
    """Most useful first: the persistent API code, then the latest embed code."""
    account = get_account(user_id) or {}
    codes = [account.get("api_user_code"), account.get("last_embed_user_code")]
    codes += list(reversed(account.get("user_codes") or []))
    seen, ordered = set(), []
    for c in codes:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def user_id_for_code(user_code: str | None) -> ObjectId | None:
    if not user_code:
        return None
    account = get_db().oro_accounts.find_one({"user_codes": user_code}, {"user_id": 1})
    return account["user_id"] if account else None


def _num(v):
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return n if n == n else None


def _time(v) -> datetime | None:
    if isinstance(v, datetime):
        return as_utc(v)
    if isinstance(v, str) and v:
        try:
            return as_utc(datetime.fromisoformat(v.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def record_transaction(raw: dict, *, user_id: ObjectId | None, source: str, kind: str | None = None) -> dict | None:
    tx_id = raw.get("transaction_id") or raw.get("id") or raw.get("order_id")
    if not tx_id:
        return None
    asset = raw.get("asset_type") or raw.get("metal") or raw.get("asset")
    fields = {
        "user_code": raw.get("user_code"),
        "type": kind or raw.get("type") or raw.get("transaction_type") or "transaction",
        "asset_type": asset if asset in ("gold", "silver") else None,
        "amount_inr": _num(raw.get("amount_inr") or raw.get("amount") or raw.get("net_amount_inr")),
        "quantity_grams": _num(raw.get("quantity_grams") or raw.get("grams") or raw.get("quantity")),
        "rate_inr_per_gram": _num(raw.get("rate_inr_per_gram")),
        "status": raw.get("status"),
        "occurred_at": _time(raw.get("created_at") or raw.get("timestamp")) or utcnow(),
        "updated_at": utcnow(),
    }
    fields = {k: v for k, v in fields.items() if v is not None}
    if user_id:
        fields["user_id"] = user_id
    return get_db().oro_transactions.find_one_and_update(
        {"transaction_id": str(tx_id)},
        {
            "$set": fields,
            "$setOnInsert": {"transaction_id": str(tx_id), "source": source, "created_at": utcnow()},
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )


def read_holding(portfolio: dict | None, metal: str) -> dict | None:
    """The portfolio payload isn't pinned down in the public docs; read the common shapes."""
    if not isinstance(portfolio, dict):
        return None
    containers = [portfolio] + [
        portfolio[k] for k in ("balances", "holdings", "portfolio", "assets") if isinstance(portfolio.get(k), dict)
    ]
    for c in containers:
        node = c.get(metal)
        if isinstance(node, dict):
            grams = _num(
                node.get("grams") or node.get("quantity_grams") or node.get("balance_grams")
                or node.get("quantity") or node.get("balance")
            )
            if grams is not None:
                return {
                    "grams": grams,
                    "value_inr": _num(node.get("current_value_inr") or node.get("value_inr") or node.get("current_value")),
                    "invested_inr": _num(node.get("invested_inr") or node.get("invested_amount_inr") or node.get("invested")),
                }
        flat = _num(c.get(f"{metal}_grams") or c.get(f"{metal}_balance"))
        if flat is not None:
            return {"grams": flat, "value_inr": _num(c.get(f"{metal}_value_inr")), "invested_inr": None}
        if _num(node) is not None:
            return {"grams": _num(node), "value_inr": None, "invested_inr": None}
    return None
