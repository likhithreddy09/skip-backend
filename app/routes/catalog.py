from flask import Blueprint, request

from ..db import get_db
from ..errors import ApiError, ok
from ..services.catalog_prices import DATASETS, list_prices

bp = Blueprint("catalog", __name__, url_prefix="/catalog")


@bp.get("/prices")
def prices():
    state = (request.args.get("state") or "telangana").strip().lower()
    if state not in DATASETS:
        raise ApiError(404, "STATE_NOT_SUPPORTED", f"No price list for '{state}' yet.")
    items = list_prices(get_db(), state)
    updated_at = max((i["updated_at"] for i in items), default=None)
    body, status = ok({"state": state, "as_of": DATASETS[state].AS_OF, "updated_at": updated_at, "items": items})
    body.headers["Cache-Control"] = "public, max-age=3600"
    return body, status


@bp.get("/states")
def states():
    return ok({"states": sorted(DATASETS)})
