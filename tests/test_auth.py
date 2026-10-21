from tests.conftest import login


def test_health(client):
    body = client.get("/api/v1/health").get_json()
    assert body["success"] and body["data"]["database"] == "mock"


def test_otp_login_creates_user(client):
    tokens, headers = login(client, "+91 98765 43210")
    me = client.get("/api/v1/me", headers=headers).get_json()["data"]
    assert me["mobile"] == "9876543210"
    assert me["name"] == "Anya"
    assert tokens["token_type"] == "Bearer"


def test_invalid_mobile_rejected(client):
    res = client.post("/api/v1/auth/otp/send", json={"mobile": "12345"})
    assert res.status_code == 422
    assert res.get_json()["error"]["code"] == "INVALID_MOBILE"


def test_wrong_code_then_lockout(client):
    client.post("/api/v1/auth/otp/send", json={"mobile": "9000000001"})
    for _ in range(5):
        res = client.post("/api/v1/auth/otp/verify", json={"mobile": "9000000001", "code": "000000"})
        assert res.get_json()["error"]["code"] in ("OTP_INVALID",)
    res = client.post("/api/v1/auth/otp/verify", json={"mobile": "9000000001", "code": "000000"})
    assert res.status_code == 429


def test_resend_cooldown(client):
    client.post("/api/v1/auth/otp/send", json={"mobile": "9000000002"})
    res = client.post("/api/v1/auth/otp/send", json={"mobile": "9000000002"})
    assert res.status_code == 429
    assert res.get_json()["error"]["code"] == "OTP_COOLDOWN"


def test_code_is_single_use(client):
    sent = client.post("/api/v1/auth/otp/send", json={"mobile": "9000000003"}).get_json()
    code = sent["data"]["dev_code"]
    assert client.post("/api/v1/auth/otp/verify", json={"mobile": "9000000003", "code": code}).status_code == 200
    assert client.post("/api/v1/auth/otp/verify", json={"mobile": "9000000003", "code": code}).status_code == 400


def test_refresh_rotation_and_reuse_detection(client):
    tokens, _ = login(client)
    first = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert first.status_code == 200
    new_refresh = first.get_json()["data"]["tokens"]["refresh_token"]

    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert replay.status_code == 401
    # Reuse revoked the whole family, including the newer token.
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh}).status_code == 401


def test_requires_auth(client):
    res = client.get("/api/v1/me")
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_delete_account(client, auth):
    assert client.delete("/api/v1/me", headers=auth).status_code == 200
    assert client.get("/api/v1/me", headers=auth).status_code == 401


def test_otp_disabled_provider(app):
    app.config["OTP_PROVIDER"] = "disabled"
    res = app.test_client().post("/api/v1/auth/otp/send", json={"mobile": "9876543210"})
    assert res.status_code == 503
    assert res.get_json()["error"]["code"] == "OTP_DISABLED"
