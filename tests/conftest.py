import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app  # noqa: E402
from app.services import oropocket  # noqa: E402

WEBHOOK_SECRET = "whsec_test"


@pytest.fixture
def app():
    oropocket.clear_cache()
    app = create_app(
        {
            "TESTING": True,
            "APP_ENV": "development",
            "IS_PRODUCTION": False,
            "MONGODB_URI": "",
            "RATELIMIT_ENABLED": False,
            "OTP_PROVIDER": "console",
            "OROPOCKET_API_KEY": "oro_test_dummy",
            "OROPOCKET_MODE": "sandbox",
            "OROPOCKET_WEBHOOK_SECRET": WEBHOOK_SECRET,
            "ENABLE_RAW_TRADING": False,
        }
    )
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, mobile="9876543210", name="Anya"):
    sent = client.post("/api/v1/auth/otp/send", json={"mobile": mobile}).get_json()
    code = sent["data"]["dev_code"]
    res = client.post("/api/v1/auth/otp/verify", json={"mobile": mobile, "code": code, "name": name})
    body = res.get_json()["data"]
    return body["tokens"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


@pytest.fixture
def auth(client):
    _, headers = login(client)
    return headers


class FakeOro:
    """Stands in for oropocket.call; register responses per (method, path)."""

    def __init__(self):
        self.routes = {}
        self.calls = []

    def on(self, method, path, status=200, data=None, error=None):
        body = {"success": error is None, "mode": "sandbox"}
        body["data" if error is None else "error"] = data if error is None else error
        self.routes[(method, path)] = oropocket.OroResponse(status, body)

    def __call__(self, method, path, *, json=None, params=None, idempotency_key=None):
        self.calls.append({"method": method, "path": path, "json": json, "idempotency_key": idempotency_key})
        return self.routes.get(
            (method, path),
            oropocket.OroResponse(404, {"success": False, "error": {"code": "NOT_FOUND", "message": path}}),
        )


@pytest.fixture
def oro(monkeypatch):
    fake = FakeOro()
    monkeypatch.setattr(oropocket, "call", fake)
    return fake
