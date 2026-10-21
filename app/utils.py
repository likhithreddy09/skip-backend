import re
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from flask import request
from flask.json.provider import DefaultJSONProvider
from pydantic import BaseModel

from .errors import ApiError

MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def normalize_mobile(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if MOBILE_RE.match(digits) else None


def mask_mobile(mobile: str) -> str:
    return f"XXXXXX{mobile[-4:]}"


def parse_object_id(value: str, what: str = "id") -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise ApiError(404, "NOT_FOUND", f"Unknown {what}.")


def parse_body(model: type[BaseModel]):
    data = request.get_json(silent=True)
    if data is None:
        if request.content_length:
            raise ApiError(400, "INVALID_JSON", "Body must be valid JSON.")
        data = {}
    return model.model_validate(data)


def query_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(request.args.get(name, default))
    except ValueError:
        raise ApiError(400, "INVALID_QUERY", f"{name} must be an integer.")
    return max(lo, min(hi, value))


def query_datetime(name: str) -> datetime | None:
    raw = request.args.get(name)
    if not raw:
        return None
    try:
        return as_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        raise ApiError(400, "INVALID_QUERY", f"{name} must be an ISO-8601 timestamp.")


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return as_utc(value).isoformat().replace("+00:00", "Z")


class JSONProvider(DefaultJSONProvider):
    sort_keys = False

    @staticmethod
    def default(o):
        if isinstance(o, ObjectId):
            return str(o)
        if isinstance(o, datetime):
            return iso(o)
        return DefaultJSONProvider.default(o)
