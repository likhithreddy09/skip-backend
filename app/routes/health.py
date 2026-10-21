from flask import Blueprint, current_app

from ..db import get_db
from ..errors import ok

bp = Blueprint("health", __name__)


@bp.get("/health")
def health():
    cfg = current_app.config
    try:
        get_db().command("ping")
        db_status = "mock" if current_app.extensions["mongo_is_mock"] else "ok"
    except Exception:
        db_status = "down"
    return ok(
        {
            "status": "ok" if db_status != "down" else "degraded",
            "env": cfg["APP_ENV"],
            "database": db_status,
            "gold_mode": cfg["OROPOCKET_MODE"],
            "webhooks_configured": bool(cfg["OROPOCKET_WEBHOOK_SECRET"]),
            "otp_provider": cfg["OTP_PROVIDER"],
        }
    )
