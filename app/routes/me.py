from flask import Blueprint, request
from pydantic import BaseModel
from pymongo import DESCENDING, ReturnDocument, UpdateOne

from ..db import RECORD_COLLECTIONS, get_db
from ..errors import ApiError, ok
from ..schemas import (
    AccountPatch,
    BulkIn,
    Deposit,
    HabitLog,
    Profile,
    ProfilePatch,
    Purchase,
    SettingsPatch,
    SipPlan,
    SkipQueueItem,
    StateImport,
)
from ..security import current_user, require_auth, revoke_all_sessions
from ..serializers import record_out, settings_out, user_out
from ..utils import parse_body, query_datetime, query_int, utcnow

bp = Blueprint("me", __name__, url_prefix="/me")

# URL segment → (collection, model)
RESOURCES: dict[str, tuple[str, type[BaseModel]]] = {
    "logs": ("habit_logs", HabitLog),
    "deposits": ("deposits", Deposit),
    "skip-queue": ("skip_queue", SkipQueueItem),
    "purchases": ("purchases", Purchase),
    "sip-plans": ("sip_plans", SipPlan),
}


def _resource(name: str) -> tuple[str, type[BaseModel]]:
    if name not in RESOURCES:
        raise ApiError(404, "NOT_FOUND", f"Unknown resource '{name}'.")
    return RESOURCES[name]


def _uid():
    return current_user()["_id"]


# --- account -------------------------------------------------------------------


@bp.get("")
@require_auth
def get_me():
    user = current_user()
    return ok({**user_out(user), "profile": user.get("profile"), "settings": settings_out(user)})


@bp.patch("")
@require_auth
def patch_me():
    changes = parse_body(AccountPatch).model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(422, "NOTHING_TO_UPDATE", "Send name and/or email.")
    user = get_db().users.find_one_and_update(
        {"_id": _uid()},
        {"$set": {**changes, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return ok(user_out(user))


@bp.delete("")
@require_auth
def delete_me():
    """Erases SkipMint data. Gold held with OroPocket stays in the user's OroPocket account."""
    db = get_db()
    uid = _uid()
    for name in RECORD_COLLECTIONS:
        db[name].delete_many({"user_id": uid})
    for name in ("oro_transactions", "oro_sips", "payment_orders"):
        db[name].update_many({"user_id": uid}, {"$set": {"user_id": None}})
    db.oro_accounts.delete_one({"user_id": uid})
    revoke_all_sessions(uid)
    db.sessions.delete_many({"user_id": uid})
    db.users.delete_one({"_id": uid})
    return ok({"deleted": True})


# --- profile (habit baseline) -----------------------------------------------------


def _save_profile(profile: dict):
    user = get_db().users.find_one_and_update(
        {"_id": _uid()},
        {"$set": {"profile": profile, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    if profile.get("name") and not user.get("name"):
        get_db().users.update_one({"_id": user["_id"]}, {"$set": {"name": profile["name"]}})
    return user["profile"]


@bp.get("/profile")
@require_auth
def get_profile():
    return ok(current_user().get("profile"))


@bp.put("/profile")
@require_auth
def put_profile():
    profile = parse_body(Profile).model_dump()
    profile["started_at"] = profile["started_at"] or utcnow()
    return ok(_save_profile(profile))


@bp.patch("/profile")
@require_auth
def patch_profile():
    existing = current_user().get("profile")
    if not existing:
        raise ApiError(404, "PROFILE_NOT_FOUND", "Create the profile with PUT first.")
    changes = parse_body(ProfilePatch).model_dump(exclude_unset=True)
    merged = Profile.model_validate({**existing, **changes}).model_dump()
    return ok(_save_profile(merged))


# --- settings ----------------------------------------------------------------------


@bp.get("/settings")
@require_auth
def get_settings():
    return ok(settings_out(current_user()))


@bp.patch("/settings")
@require_auth
def patch_settings():
    changes = parse_body(SettingsPatch).model_dump(exclude_unset=True)
    if not changes:
        raise ApiError(422, "NOTHING_TO_UPDATE", "Send at least one setting.")
    user = get_db().users.find_one_and_update(
        {"_id": _uid()},
        {"$set": {**{f"settings.{k}": v for k, v in changes.items()}, "updated_at": utcnow()}},
        return_document=ReturnDocument.AFTER,
    )
    return ok(settings_out(user))


# --- records: /me/<resource> --------------------------------------------------------


def upsert_records(collection: str, models: list[BaseModel]) -> None:
    """Idempotent by the client-generated id, so offline retries never duplicate."""
    if not models:
        return
    now = utcnow()
    uid = _uid()
    ops = [
        UpdateOne(
            {"user_id": uid, "client_id": m.id},
            {
                "$set": {**m.model_dump(exclude={"id"}), "updated_at": now},
                "$setOnInsert": {"user_id": uid, "client_id": m.id, "created_at": now},
            },
            upsert=True,
        )
        for m in models
    ]
    get_db()[collection].bulk_write(ops, ordered=False)


@bp.get("/<resource>")
@require_auth
def list_records(resource: str):
    collection, _ = _resource(resource)
    limit = query_int("limit", 100, 1, 500)
    query: dict = {"user_id": _uid()}
    before = query_datetime("before")
    if before:
        query["at"] = {"$lt": before}
    since = query_datetime("updated_since")
    if since:
        query["updated_at"] = {"$gt": since}

    docs = list(get_db()[collection].find(query).sort("at", DESCENDING).limit(limit + 1))
    has_more = len(docs) > limit
    docs = docs[:limit]
    return ok(
        [record_out(d) for d in docs],
        pagination={"limit": limit, "has_more": has_more, "next_before": docs[-1]["at"] if has_more else None},
    )


@bp.post("/<resource>")
@require_auth
def create_records(resource: str):
    collection, model = _resource(resource)
    raw = request.get_json(silent=True)
    if isinstance(raw, dict) and "items" in raw:
        items = [model.model_validate(i) for i in parse_body(BulkIn).items]
    else:
        items = [parse_body(model)]
    upsert_records(collection, items)
    ids = [m.id for m in items]
    docs = get_db()[collection].find({"user_id": _uid(), "client_id": {"$in": ids}})
    return ok([record_out(d) for d in docs], status=201)


def _find_record(collection: str, record_id: str) -> dict:
    doc = get_db()[collection].find_one({"user_id": _uid(), "client_id": record_id})
    if not doc:
        raise ApiError(404, "NOT_FOUND", "Record not found.")
    return doc


@bp.get("/<resource>/<record_id>")
@require_auth
def get_record(resource: str, record_id: str):
    collection, _ = _resource(resource)
    return ok(record_out(_find_record(collection, record_id)))


@bp.patch("/<resource>/<record_id>")
@require_auth
def patch_record(resource: str, record_id: str):
    collection, model = _resource(resource)
    existing = record_out(_find_record(collection, record_id))
    changes = request.get_json(silent=True)
    if not isinstance(changes, dict) or not changes:
        raise ApiError(422, "NOTHING_TO_UPDATE", "Send the fields to change.")
    changes.pop("id", None)
    merged = model.model_validate({**existing, **changes, "id": record_id})
    upsert_records(collection, [merged])
    return ok(record_out(_find_record(collection, record_id)))


@bp.delete("/<resource>/<record_id>")
@require_auth
def delete_record(resource: str, record_id: str):
    collection, _ = _resource(resource)
    result = get_db()[collection].delete_one({"user_id": _uid(), "client_id": record_id})
    if not result.deleted_count:
        raise ApiError(404, "NOT_FOUND", "Record not found.")
    return ok({"deleted": True})


@bp.delete("/<resource>")
@require_auth
def clear_records(resource: str):
    collection, _ = _resource(resource)
    if request.args.get("confirm") != "true":
        raise ApiError(400, "CONFIRM_REQUIRED", "Add ?confirm=true to delete every record.")
    result = get_db()[collection].delete_many({"user_id": _uid()})
    return ok({"deleted": result.deleted_count})


# --- full state: app boot + first-login import ----------------------------------------

SNAPSHOT_LIMITS = {"habit_logs": 5000, "deposits": 1000, "skip_queue": 1000, "purchases": 1000, "sip_plans": 200}


@bp.get("/state")
@require_auth
def get_state():
    db = get_db()
    user = current_user()
    records = {
        name: [
            record_out(d)
            for d in db[name].find({"user_id": user["_id"]}).sort("at", DESCENDING).limit(limit)
        ]
        for name, limit in SNAPSHOT_LIMITS.items()
    }
    return ok(
        {
            "user": user_out(user),
            "profile": user.get("profile"),
            "settings": settings_out(user),
            "logs": records["habit_logs"],
            "deposits": records["deposits"],
            "skip_queue": records["skip_queue"],
            "purchases": records["purchases"],
            "sip_plans": records["sip_plans"],
            "server_time": utcnow(),
        }
    )


@bp.post("/state/import")
@require_auth
def import_state():
    """Merges the app's local data into the account. Safe to call more than once."""
    body = parse_body(StateImport)
    user = current_user()

    upsert_records("habit_logs", body.logs)
    upsert_records("deposits", body.deposits)
    upsert_records("skip_queue", body.skip_queue)
    upsert_records("purchases", body.purchases)
    upsert_records("sip_plans", body.sips)

    settings = body.innovations.model_dump(exclude_none=True) if body.innovations else {}
    for key in ("savings_goal", "last_check_in_date", "game_wins_today", "game_wins_date"):
        value = getattr(body, key)
        if value is not None:
            settings[key] = value

    update: dict = {"updated_at": utcnow()}
    update.update({f"settings.{k}": v for k, v in settings.items()})
    if body.baseline and not user.get("profile"):
        profile = body.baseline.model_dump()
        profile["started_at"] = profile["started_at"] or utcnow()
        update["profile"] = profile
        if not user.get("name"):
            update["name"] = profile["name"]
    get_db().users.update_one({"_id": user["_id"]}, {"$set": update})

    return ok(
        {
            "imported": {
                "logs": len(body.logs),
                "deposits": len(body.deposits),
                "skip_queue": len(body.skip_queue),
                "purchases": len(body.purchases),
                "sip_plans": len(body.sips),
                "profile": bool(body.baseline and not user.get("profile")),
                "settings": len(settings),
            }
        }
    )
