import hashlib
import hmac
import secrets
from datetime import timedelta
from functools import wraps

import jwt
from bson import ObjectId
from flask import current_app, g, request

from .db import get_db
from .errors import ApiError
from .utils import as_utc, utcnow

JWT_ALG = "HS256"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_otp(mobile: str, code: str) -> str:
    pepper = current_app.config["OTP_PEPPER"].encode()
    return hmac.new(pepper, f"{mobile}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_access_token(user_id: ObjectId) -> tuple[str, int]:
    ttl = current_app.config["ACCESS_TOKEN_TTL_MINUTES"] * 60
    now = utcnow()
    token = jwt.encode(
        {
            "sub": str(user_id),
            "type": "access",
            "iat": now,
            "exp": now + timedelta(seconds=ttl),
            "jti": secrets.token_hex(8),
        },
        current_app.config["JWT_SECRET"],
        algorithm=JWT_ALG,
    )
    return token, ttl


def create_session(user_id: ObjectId, family: str | None = None) -> dict:
    """Refresh tokens are opaque, stored hashed, and rotated on every use."""
    refresh_token = secrets.token_urlsafe(48)
    now = utcnow()
    expires_at = now + timedelta(days=current_app.config["REFRESH_TOKEN_TTL_DAYS"])
    get_db().sessions.insert_one(
        {
            "user_id": user_id,
            "token_hash": sha256(refresh_token),
            "family": family or secrets.token_hex(12),
            "created_at": now,
            "expires_at": expires_at,
            "revoked_at": None,
            "user_agent": (request.headers.get("User-Agent") or "")[:200],
        }
    )
    access_token, access_ttl = issue_access_token(user_id)
    return {
        "access_token": access_token,
        "token_type": "Bearer",
        "expires_in": access_ttl,
        "refresh_token": refresh_token,
        "refresh_expires_at": expires_at,
    }


def rotate_session(refresh_token: str) -> dict:
    db = get_db()
    session = db.sessions.find_one({"token_hash": sha256(refresh_token)})
    if not session or as_utc(session["expires_at"]) <= utcnow():
        raise ApiError(401, "INVALID_REFRESH_TOKEN", "Session expired. Sign in again.")

    if session.get("revoked_at"):
        # A rotated token was replayed: assume theft and end the whole family.
        db.sessions.update_many(
            {"family": session["family"], "revoked_at": None},
            {"$set": {"revoked_at": utcnow(), "revoked_reason": "reuse_detected"}},
        )
        raise ApiError(401, "INVALID_REFRESH_TOKEN", "Session expired. Sign in again.")

    claimed = db.sessions.update_one(
        {"_id": session["_id"], "revoked_at": None},
        {"$set": {"revoked_at": utcnow(), "revoked_reason": "rotated"}},
    )
    if claimed.modified_count != 1:
        raise ApiError(401, "INVALID_REFRESH_TOKEN", "Session expired. Sign in again.")

    user = db.users.find_one({"_id": session["user_id"], "deleted_at": None})
    if not user:
        raise ApiError(401, "INVALID_REFRESH_TOKEN", "Account no longer exists.")
    return create_session(user["_id"], family=session["family"])


def revoke_session(refresh_token: str) -> None:
    get_db().sessions.update_one(
        {"token_hash": sha256(refresh_token), "revoked_at": None},
        {"$set": {"revoked_at": utcnow(), "revoked_reason": "logout"}},
    )


def revoke_all_sessions(user_id: ObjectId) -> None:
    get_db().sessions.update_many(
        {"user_id": user_id, "revoked_at": None},
        {"$set": {"revoked_at": utcnow(), "revoked_reason": "logout_all"}},
    )


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            raise ApiError(401, "UNAUTHORIZED", "Missing bearer token.")
        try:
            claims = jwt.decode(
                header[7:],
                current_app.config["JWT_SECRET"],
                algorithms=[JWT_ALG],
                options={"require": ["sub", "exp", "type"]},
            )
        except jwt.ExpiredSignatureError:
            raise ApiError(401, "TOKEN_EXPIRED", "Access token expired. Refresh it.")
        except jwt.PyJWTError:
            raise ApiError(401, "UNAUTHORIZED", "Invalid access token.")
        if claims.get("type") != "access" or not ObjectId.is_valid(claims["sub"]):
            raise ApiError(401, "UNAUTHORIZED", "Invalid access token.")

        user = get_db().users.find_one({"_id": ObjectId(claims["sub"]), "deleted_at": None})
        if not user:
            raise ApiError(401, "UNAUTHORIZED", "Account no longer exists.")
        g.user = user
        return fn(*args, **kwargs)

    return wrapper


def current_user() -> dict:
    return g.user
