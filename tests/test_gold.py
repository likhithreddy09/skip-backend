import hashlib
import hmac
import json
import time

from tests.conftest import WEBHOOK_SECRET

PRICES = {"gold": {"buy": 15000, "sell": 14500, "gst_percentage": 3, "final_buy_price": 15450}}
CAPS = {"partner": {"is_active": True, "live_enabled": True, "embed_enabled": True,
                    "allowed_apis": ["pricing", "users", "buy", "sell", "embed", "transactions", "balance"]}}


def test_prices_cached(client, oro):
    oro.on("GET", "/prices", data={"prices": PRICES})
    first = client.get("/api/v1/gold/prices").get_json()["data"]
    second = client.get("/api/v1/gold/prices").get_json()["data"]
    assert first["prices"]["gold"]["sell"] == 14500
    assert second["cached"] is True
    assert len([c for c in oro.calls if c["path"] == "/prices"]) == 1


def test_embed_session_uses_account_mobile(client, auth, oro):
    oro.on("POST", "/users/init", data={"user_code": "usr_e1", "embed_url": "https://connect.oropocket.com/?u=usr_e1",
                                        "expires_in_seconds": 600, "mode": "sandbox"})
    res = client.post("/api/v1/gold/embed-session",
                      json={"launch": {"screen": "sip", "metal": "gold", "amount": 500, "frequency": "weekly"},
                            "mobile": "9999999999"}, headers=auth)
    assert res.status_code == 200
    sent = oro.calls[-1]["json"]
    assert sent["mobile"] == "9876543210"  # never the client-supplied number
    assert sent["launch"]["screen"] == "sip"
    assert "user_code" not in res.get_json()["data"]


def test_embed_launch_fallback(client, auth, oro):
    calls = {"n": 0}

    def fake(method, path, *, json=None, params=None, idempotency_key=None):
        from app.services.oropocket import OroResponse
        calls["n"] += 1
        if json.get("launch"):
            return OroResponse(403, {"success": False, "error": {"code": "LAUNCH_NOT_ENABLED"}})
        return OroResponse(200, {"success": True, "data": {"user_code": "usr_e2", "embed_url": "https://x/?u=usr_e2"}})

    import app.services.oropocket as oropocket
    oropocket.call = fake
    data = client.post("/api/v1/gold/embed-session", json={"launch": {"screen": "buy"}}, headers=auth).get_json()["data"]
    assert data["launch_fallback"] is True and calls["n"] == 2


def test_payments_gated_without_capability(client, auth, oro):
    oro.on("GET", "/dashboard/me", data=CAPS)
    oro.on("GET", "/wallet", data={"available_inr": 0})
    res = client.post("/api/v1/payments/sips", json={"installment_amount_inr": 500, "frequency": "weekly",
                                                     "asset_type": "gold"}, headers=auth)
    assert res.status_code == 403
    assert res.get_json()["error"]["code"] == "CAPABILITY_NOT_ENABLED"


def test_trading_gated_by_default(client, auth, oro):
    oro.on("GET", "/dashboard/me", data=CAPS)
    oro.on("GET", "/wallet", data={"available_inr": 100000})
    res = client.post("/api/v1/gold/trades/buy/quote", json={"asset_type": "gold", "amount_inr": 100}, headers=auth)
    assert res.status_code == 403


def test_trade_quote_confirm_flow(app, client, auth, oro):
    app.config["ENABLE_RAW_TRADING"] = True
    oro.on("GET", "/dashboard/me", data=CAPS)
    oro.on("GET", "/wallet", data={"available_inr": 100000})
    oro.on("POST", "/users/init", data={"user_code": "usr_api1"})
    oro.on("POST", "/buy/quote", data={"quote_id": "tqt_1", "quantity_grams": 0.0065, "rate_inr_per_gram": 15450,
                                      "expires_in_seconds": 600})
    oro.on("POST", "/buy/confirm", data={"transaction_id": "txn_1", "status": "completed", "amount_inr": 100,
                                        "quantity_grams": 0.0065})

    quote = client.post("/api/v1/gold/trades/buy/quote", json={"asset_type": "gold", "amount_inr": 100}, headers=auth)
    assert quote.status_code == 201
    res = client.post("/api/v1/gold/trades/buy/confirm", json={"quote_id": "tqt_1"}, headers=auth)
    assert res.status_code == 200
    confirm_call = [c for c in oro.calls if c["path"] == "/buy/confirm"][0]
    assert confirm_call["idempotency_key"] == "buy-confirm-tqt_1"

    txs = client.get("/api/v1/gold/transactions?refresh=false", headers=auth).get_json()["data"]
    assert txs[0]["transaction_id"] == "txn_1" and txs[0]["type"] == "buy"


def test_cannot_confirm_someone_elses_quote(app, client, auth, oro):
    from tests.conftest import login
    app.config["ENABLE_RAW_TRADING"] = True
    oro.on("GET", "/dashboard/me", data=CAPS)
    oro.on("GET", "/wallet", data={"available_inr": 100000})
    oro.on("POST", "/users/init", data={"user_code": "usr_api1"})
    oro.on("POST", "/buy/quote", data={"quote_id": "tqt_9"})
    client.post("/api/v1/gold/trades/buy/quote", json={"asset_type": "gold", "amount_inr": 100}, headers=auth)
    _, other = login(client, "9123456780", "Ravi")
    res = client.post("/api/v1/gold/trades/buy/confirm", json={"quote_id": "tqt_9"}, headers=other)
    assert res.status_code == 404


def _signed(body: dict, ts=None, secret=WEBHOOK_SECRET):
    raw = json.dumps(body).encode()
    ts = str(ts or int(time.time()))
    sig = "sha256=" + hmac.new(secret.encode(), ts.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return raw, {"X-OroPocket-Signature": sig, "X-OroPocket-Timestamp": ts, "Content-Type": "application/json"}


def test_webhook_records_buy_for_user(client, auth, oro):
    oro.on("POST", "/users/init", data={"user_code": "usr_e5", "embed_url": "https://x/?u=usr_e5"})
    client.post("/api/v1/gold/embed-session", json={}, headers=auth)

    event = {"event": "buy.completed", "event_id": "evt_1", "mode": "sandbox",
             "data": {"user_code": "usr_e5", "asset_type": "gold", "amount_inr": 1000,
                      "quantity_grams": 0.0647, "transaction_id": "txn_w1", "status": "completed"}}
    raw, headers = _signed(event)
    assert client.post("/api/v1/webhooks/oropocket", data=raw, headers=headers).status_code == 200
    dup = client.post("/api/v1/webhooks/oropocket", data=raw, headers=headers).get_json()
    assert dup["data"]["duplicate"] is True

    txs = client.get("/api/v1/gold/transactions?refresh=false", headers=auth).get_json()["data"]
    assert len(txs) == 1 and txs[0]["quantity_grams"] == 0.0647


def test_webhook_rejects_bad_signature_and_replay(client):
    event = {"event": "test.ping", "event_id": "evt_x", "data": {}}
    raw, headers = _signed(event, secret="wrong")
    assert client.post("/api/v1/webhooks/oropocket", data=raw, headers=headers).status_code == 401
    raw, headers = _signed(event, ts=int(time.time()) - 900)
    assert client.post("/api/v1/webhooks/oropocket", data=raw, headers=headers).status_code == 401
