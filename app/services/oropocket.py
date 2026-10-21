"""OroPocket Partner API client. Docs: https://developers.oropocket.com/docs/"""

import logging
import threading
import time

import requests
from flask import current_app

from ..errors import ApiError

log = logging.getLogger(__name__)

TIMEOUT = 15
PRICE_TTL = 60
PRICE_STALE_MAX = 60 * 60
CAPS_TTL = 5 * 60

_session = requests.Session()
_lock = threading.Lock()
_cache: dict[str, tuple[float, object]] = {}


class OroResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self.body = body

    @property
    def ok(self) -> bool:
        return self.status < 400 and self.body.get("success") is not False

    @property
    def data(self):
        return self.body.get("data")

    def raise_for_error(self) -> "OroResponse":
        if not self.ok:
            err = self.body.get("error") or {}
            raise ApiError(
                self.status if self.status >= 400 else 502,
                err.get("code") or "OROPOCKET_ERROR",
                err.get("message") or "OroPocket request failed.",
                err.get("details"),
            )
        return self


def _require_key() -> str:
    key = current_app.config["OROPOCKET_API_KEY"]
    if not key:
        raise ApiError(503, "GOLD_NOT_CONFIGURED", "OROPOCKET_API_KEY is not set on the server.")
    return key


def call(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    idempotency_key: str | None = None,
) -> OroResponse:
    """GETs and idempotent POSTs are retried on network errors, 429 and 5xx:
    OroPocket replays the original response for a repeated Idempotency-Key."""
    key = _require_key()
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    attempts = 3 if method == "GET" or idempotency_key else 1
    url = f"{current_app.config['OROPOCKET_BASE_URL']}{path}"

    last = OroResponse(502, {"success": False, "error": {"code": "UPSTREAM_ERROR"}})
    for i in range(attempts):
        try:
            res = _session.request(
                method, url, json=json, params=params, headers=headers, timeout=TIMEOUT
            )
            try:
                body = res.json()
            except ValueError:
                body = {"success": False, "error": {"code": "UPSTREAM_ERROR", "message": res.text[:200]}}
            last = OroResponse(res.status_code, body)
            if res.status_code != 429 and res.status_code < 500:
                return last
            retry_after = res.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.4 * 2**i
        except requests.RequestException as e:
            log.warning("OroPocket %s %s failed: %s", method, path, e)
            last = OroResponse(
                502,
                {"success": False, "error": {"code": "UPSTREAM_ERROR", "message": "Gold service unreachable."}},
            )
            delay = 0.4 * 2**i
        if i < attempts - 1:
            time.sleep(min(delay, 5))
    return last


def _cached(key: str, ttl: float, loader, stale_max: float | None = None):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1], True, False
    try:
        value = loader()
    except ApiError:
        if hit and stale_max and now - hit[0] < stale_max:
            return hit[1], True, True
        raise
    with _lock:
        _cache[key] = (time.time(), value)
    return value, False, False


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def get_prices() -> tuple[dict, bool, bool]:
    """OroPocket refreshes rates roughly every 30 minutes; a short cache is safe."""
    return _cached(
        "prices",
        PRICE_TTL,
        lambda: call("GET", "/prices").raise_for_error().data["prices"],
        stale_max=PRICE_STALE_MAX,
    )


def get_capabilities(force: bool = False) -> dict:
    if force:
        with _lock:
            _cache.pop("capabilities", None)

    def load():
        me = call("GET", "/dashboard/me").raise_for_error().data["partner"]
        wallet = call("GET", "/wallet")
        allowed = list(me.get("allowed_apis") or [])
        available = float((wallet.data or {}).get("available_inr") or 0) if wallet.ok else 0.0
        raw = current_app.config["ENABLE_RAW_TRADING"]
        return {
            "mode": current_app.config["OROPOCKET_MODE"],
            "active": bool(me.get("is_active")),
            "live_enabled": bool(me.get("live_enabled")),
            "embed_enabled": bool(me.get("embed_enabled")) and "embed" in allowed,
            "allowed_apis": allowed,
            "payments_enabled": "payments" in allowed,
            "raw_trading_enabled": raw,
            "float_available_inr": available,
            "can_raw_buy": raw and "buy" in allowed and available > 0,
            "can_raw_sell": raw and "sell" in allowed,
        }

    value, _, _ = _cached("capabilities", CAPS_TTL, load)
    return value


def require_capability(check, message: str) -> dict:
    caps = get_capabilities()
    if not check(caps):
        raise ApiError(403, "CAPABILITY_NOT_ENABLED", message, {"allowed_apis": caps["allowed_apis"]})
    return caps


LAUNCH_FALLBACK_CODES = {
    "LAUNCH_NOT_ENABLED",
    "LAUNCH_SCREEN_UNAVAILABLE",
    "INVALID_LAUNCH",
    "LAUNCH_NOT_READY",
}


def init_embed(payload: dict) -> dict:
    """POST /users/init flow=embed. Retries without `launch` when deep links are off."""
    res = call("POST", "/users/init", json=payload)
    if not res.ok and payload.get("launch"):
        code = (res.body.get("error") or {}).get("code")
        if code in LAUNCH_FALLBACK_CODES:
            retry_payload = {k: v for k, v in payload.items() if k != "launch"}
            data = call("POST", "/users/init", json=retry_payload).raise_for_error().data
            return {**data, "launch_fallback": True, "launch_error": code}
    return res.raise_for_error().data
