import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import create_app  # noqa: E402
from app.routes import auth as auth_routes  # noqa: E402
from app.services import oropocket  # noqa: E402
from app.services.google import GoogleIdentity  # noqa: E402

WEBHOOK_SECRET = "whsec_test"
TEST_GOOGLE_CLIENT_ID = "test-client.apps.googleusercontent.com"


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
            "GOOGLE_CLIENT_IDS": [TEST_GOOGLE_CLIENT_ID],
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


# Real Google ID tokens are long JWTs; the schema enforces a 20-char floor.
# Tests encode the account id after this prefix to clear that without clutter.
_FAKE_TOKEN_PREFIX = "fake-google-id-token::"


def fake_id_token(sub: str) -> str:
    return f"{_FAKE_TOKEN_PREFIX}{sub}"


@pytest.fixture(autouse=True)
def fake_google(monkeypatch):
    """Verify Google ID tokens without hitting Google.

    The test token carries the Google account id (sub) after a fixed prefix, so
    different accounts produce different users. Use sub ``bad`` to simulate rejection.
    """

    def _verify(token: str) -> GoogleIdentity:
        from app.errors import ApiError

        sub = token[len(_FAKE_TOKEN_PREFIX):] if token.startswith(_FAKE_TOKEN_PREFIX) else token
        if sub == "bad":
            raise ApiError(401, "GOOGLE_TOKEN_INVALID", "Could not verify Google sign-in. Try again.")
        return GoogleIdentity(
            {
                "sub": sub,
                "email": f"{sub}@example.com",
                "email_verified": True,
                "name": "Anya",
                "picture": "https://example.com/a.png",
            }
        )

    monkeypatch.setattr(auth_routes, "verify_google_id_token", _verify)


def login(client, sub="google-user-1", name="Anya"):
    res = client.post("/api/v1/auth/google", json={"idToken": fake_id_token(sub)})
    body = res.get_json()["data"]
    return body["tokens"], {"Authorization": f"Bearer {body['tokens']['access_token']}"}


def login_with_mobile(client, sub="google-user-1", mobile="9876543210"):
    """Google user who has since added a mobile number (needed for gold flows)."""
    _, headers = login(client, sub=sub)
    client.patch("/api/v1/me", json={"mobile": mobile}, headers=headers)
    return headers


@pytest.fixture
def gold_auth(client):
    """Authed headers for a user who has added a mobile (required by gold flows)."""
    return login_with_mobile(client)


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
