import hmac
import secrets
from datetime import timedelta

from flask import Blueprint, current_app
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..db import get_db
from ..errors import ApiError, ok
from ..extensions import limiter
from ..schemas import LogoutIn, OtpSendIn, OtpVerifyIn, RefreshIn
from ..security import (
    create_session,
    current_user,
    hash_otp,
    require_auth,
    revoke_all_sessions,
    revoke_session,
    rotate_session,
)
from ..serializers import user_out
from ..services.sms import send_otp_sms
from ..utils import as_utc, mask_mobile, normalize_mobile, parse_body, utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _mobile(raw: str) -> str:
    mobile = normalize_mobile(raw)
    if not mobile:
        raise ApiError(422, "INVALID_MOBILE", "Enter a valid 10-digit Indian mobile number.")
    return mobile


@bp.post("/otp/send")
@limiter.limit("10 per 15 minutes")
def send_otp():
    body = parse_body(OtpSendIn)
    mobile = _mobile(body.mobile)
    cfg = current_app.config
    db = get_db()
    now = utcnow()

    existing = db.otp_requests.find_one({"mobile": mobile})
    if existing:
        since_last = (now - as_utc(existing["last_sent_at"])).total_seconds()
        if since_last < cfg["OTP_RESEND_COOLDOWN_SECONDS"]:
            wait = int(cfg["OTP_RESEND_COOLDOWN_SECONDS"] - since_last) + 1
            raise ApiError(429, "OTP_COOLDOWN", f"Wait {wait}s before requesting another code.",
                           {"retry_after_seconds": wait})
        window_age = (now - as_utc(existing["window_started_at"])).total_seconds()
        in_window = window_age < cfg["OTP_SEND_WINDOW_SECONDS"]
        if in_window and existing["send_count"] >= cfg["OTP_MAX_SENDS_PER_WINDOW"]:
            wait = int(cfg["OTP_SEND_WINDOW_SECONDS"] - window_age) + 1
            raise ApiError(429, "OTP_LIMIT", "Too many codes requested. Try again later.",
                           {"retry_after_seconds": wait})
    else:
        in_window = False

    code = "".join(secrets.choice("0123456789") for _ in range(cfg["OTP_LENGTH"]))
    send_otp_sms(mobile, code)

    db.otp_requests.update_one(
        {"mobile": mobile},
        {
            "$set": {
                "code_hash": hash_otp(mobile, code),
                "expires_at": now + timedelta(seconds=cfg["OTP_TTL_SECONDS"]),
                "attempts": 0,
                "last_sent_at": now,
                "purge_at": now + timedelta(days=1),
                "send_count": existing["send_count"] + 1 if in_window else 1,
                **({} if in_window else {"window_started_at": now}),
            },
        },
        upsert=True,
    )

    data = {
        "mobile_masked": mask_mobile(mobile),
        "expires_in_seconds": cfg["OTP_TTL_SECONDS"],
        "resend_after_seconds": cfg["OTP_RESEND_COOLDOWN_SECONDS"],
        "code_length": cfg["OTP_LENGTH"],
    }
    if not cfg["IS_PRODUCTION"] and cfg["OTP_PROVIDER"] == "console":
        data["dev_code"] = code
    return ok(data)


@bp.post("/otp/verify")
@limiter.limit("20 per 15 minutes")
def verify_otp():
    body = parse_body(OtpVerifyIn)
    mobile = _mobile(body.mobile)
    db = get_db()
    now = utcnow()

    otp = db.otp_requests.find_one_and_update(
        {"mobile": mobile},
        {"$inc": {"attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )
    if not otp or not otp.get("code_hash"):
        raise ApiError(400, "OTP_NOT_REQUESTED", "Request a code first.")
    if as_utc(otp["expires_at"]) <= now:
        raise ApiError(400, "OTP_EXPIRED", "Code expired. Request a new one.")
    if otp["attempts"] > current_app.config["OTP_MAX_ATTEMPTS"]:
        db.otp_requests.update_one({"_id": otp["_id"]}, {"$set": {"code_hash": None}})
        raise ApiError(429, "OTP_ATTEMPTS_EXCEEDED", "Too many wrong attempts. Request a new code.")
    if not hmac.compare_digest(otp["code_hash"], hash_otp(mobile, body.code)):
        left = current_app.config["OTP_MAX_ATTEMPTS"] - otp["attempts"]
        raise ApiError(400, "OTP_INVALID", "Incorrect code.", {"attempts_left": max(0, left)})

    db.otp_requests.update_one({"_id": otp["_id"]}, {"$set": {"code_hash": None}})

    is_new = False
    user = db.users.find_one({"mobile": mobile})
    if not user:
        doc = {
            "mobile": mobile,
            "name": body.name,
            "email": None,
            "profile": None,
            "settings": {},
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
            "deleted_at": None,
        }
        try:
            doc["_id"] = db.users.insert_one(doc).inserted_id
            user, is_new = doc, True
        except DuplicateKeyError:
            user = db.users.find_one({"mobile": mobile})
    if not is_new:
        user = db.users.find_one_and_update(
            {"_id": user["_id"]},
            {"$set": {"last_login_at": now}},
            return_document=ReturnDocument.AFTER,
        )

    return ok({"user": user_out(user), "is_new_user": is_new, "tokens": create_session(user["_id"])})


@bp.post("/refresh")
@limiter.limit("60 per minute")
def refresh():
    body = parse_body(RefreshIn)
    return ok({"tokens": rotate_session(body.refresh_token)})


@bp.post("/logout")
@require_auth
def logout():
    body = parse_body(LogoutIn)
    if body.all_devices:
        revoke_all_sessions(current_user()["_id"])
    elif body.refresh_token:
        revoke_session(body.refresh_token)
    return ok({"logged_out": True})
