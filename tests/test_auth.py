from tests.conftest import fake_id_token, login


def test_health(client):
    body = client.get("/api/v1/health").get_json()
    assert body["success"] and body["data"]["database"] == "mock"
    assert body["data"]["auth"] == "google"


def test_google_login_creates_user(client):
    tokens, headers = login(client, sub="google-abc")
    me = client.get("/api/v1/me", headers=headers).get_json()["data"]
    assert me["email"] == "google-abc@example.com"
    assert me["name"] == "Anya"
    assert me["mobile"] is None
    assert tokens["token_type"] == "Bearer"


def test_google_login_is_idempotent_per_account(client):
    first, _ = login(client, sub="same-sub")
    second, _ = login(client, sub="same-sub")
    # Same Google account signs in twice -> same user, fresh session each time.
    me1 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {first['access_token']}"})
    me2 = client.get("/api/v1/me", headers={"Authorization": f"Bearer {second['access_token']}"})
    assert me1.get_json()["data"]["id"] == me2.get_json()["data"]["id"]


def test_different_accounts_are_different_users(client):
    _, a = login(client, sub="user-a")
    _, b = login(client, sub="user-b")
    id_a = client.get("/api/v1/me", headers=a).get_json()["data"]["id"]
    id_b = client.get("/api/v1/me", headers=b).get_json()["data"]["id"]
    assert id_a != id_b


def test_is_new_user_flag(client):
    first = client.post("/api/v1/auth/google", json={"idToken": fake_id_token("brand-new")}).get_json()["data"]
    assert first["is_new_user"] is True
    again = client.post("/api/v1/auth/google", json={"idToken": fake_id_token("brand-new")}).get_json()["data"]
    assert again["is_new_user"] is False


def test_invalid_google_token_rejected(client):
    res = client.post("/api/v1/auth/google", json={"idToken": fake_id_token("bad")})
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "GOOGLE_TOKEN_INVALID"


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
