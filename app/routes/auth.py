from flask import Blueprint
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from ..db import get_db
from ..errors import ok
from ..extensions import limiter
from ..schemas import GoogleSignInIn, LogoutIn, RefreshIn
from ..security import (
    create_session,
    current_user,
    require_auth,
    revoke_all_sessions,
    revoke_session,
    rotate_session,
)
from ..serializers import user_out
from ..services.google import verify_google_id_token
from ..utils import parse_body, utcnow

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.post("/google")
@limiter.limit("20 per 5 minutes")
def google_sign_in():
    """Exchange a Google ID token for a SkipMint session.

    Users are keyed by their Google account id (``google_sub``). A returning
    user is matched on that id; a first-time user gets a new account.
    """
    body = parse_body(GoogleSignInIn)
    identity = verify_google_id_token(body.id_token)
    db = get_db()
    now = utcnow()

    is_new = False
    user = db.users.find_one({"google_sub": identity.sub})
    if not user:
        doc = {
            "google_sub": identity.sub,
            "email": identity.email,
            "email_verified": identity.email_verified,
            "name": identity.name,
            "picture": identity.picture,
            "mobile": None,
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
            # Lost a race with a concurrent first sign-in for the same account.
            user = db.users.find_one({"google_sub": identity.sub})

    if not is_new:
        # Keep the latest Google profile details and bump last login.
        user = db.users.find_one_and_update(
            {"_id": user["_id"]},
            {
                "$set": {
                    "last_login_at": now,
                    "email": identity.email,
                    "email_verified": identity.email_verified,
                    "name": user.get("name") or identity.name,
                    "picture": identity.picture,
                }
            },
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
