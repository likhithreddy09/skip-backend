from .schemas import DEFAULT_SETTINGS
from .utils import mask_mobile


def user_out(user: dict) -> dict:
    mobile = user.get("mobile")
    return {
        "id": str(user["_id"]),
        "mobile": mobile,
        "mobile_masked": mask_mobile(mobile) if mobile else None,
        "name": user.get("name"),
        "email": user.get("email"),
        "picture": user.get("picture"),
        "created_at": user["created_at"],
        "last_login_at": user.get("last_login_at"),
        "has_profile": bool(user.get("profile")),
    }


def settings_out(user: dict) -> dict:
    return {**DEFAULT_SETTINGS, **(user.get("settings") or {})}


def record_out(doc: dict) -> dict:
    out = {k: v for k, v in doc.items() if k not in {"_id", "user_id", "client_id"}}
    return {"id": doc["client_id"], **out}
