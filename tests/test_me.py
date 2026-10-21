from tests.conftest import login

PROFILE = {
    "mode": "reduce",
    "name": "Anya",
    "cigarettesPerDay": 10,
    "costPerCigarette": 18,
    "trackDrinking": True,
    "createdAt": "2026-10-01T10:00:00.000Z",
}


def test_profile_put_and_patch(client, auth):
    res = client.put("/api/v1/me/profile", json=PROFILE, headers=auth)
    assert res.status_code == 200
    assert res.get_json()["data"]["cigarettes_per_day"] == 10

    res = client.patch("/api/v1/me/profile", json={"cigarettes_per_day": 6}, headers=auth)
    data = res.get_json()["data"]
    assert data["cigarettes_per_day"] == 6 and data["mode"] == "reduce"


def test_profile_validation(client, auth):
    res = client.put("/api/v1/me/profile", json={**PROFILE, "mode": "nope"}, headers=auth)
    assert res.status_code == 422
    assert res.get_json()["error"]["code"] == "VALIDATION_ERROR"


def test_settings_defaults_and_patch(client, auth):
    data = client.get("/api/v1/me/settings", headers=auth).get_json()["data"]
    assert data["city"] == "Bengaluru"
    data = client.patch("/api/v1/me/settings", json={"city": "Pune", "savingsGoal": 5000}, headers=auth).get_json()["data"]
    assert data["city"] == "Pune" and data["savings_goal"] == 5000


def test_records_idempotent_crud(client, auth):
    log = {"id": "log_1", "kind": "skipped", "count": 1, "at": "2026-10-20T08:00:00Z", "mood": "craving"}
    assert client.post("/api/v1/me/logs", json=log, headers=auth).status_code == 201
    assert client.post("/api/v1/me/logs", json=log, headers=auth).status_code == 201  # retry is safe

    items = client.get("/api/v1/me/logs", headers=auth).get_json()["data"]
    assert len(items) == 1 and items[0]["id"] == "log_1"

    res = client.patch("/api/v1/me/logs/log_1", json={"count": 3}, headers=auth)
    assert res.get_json()["data"]["count"] == 3

    assert client.delete("/api/v1/me/logs/log_1", headers=auth).status_code == 200
    assert client.get("/api/v1/me/logs/log_1", headers=auth).status_code == 404


def test_bulk_and_pagination(client, auth):
    items = [{"id": f"d{i}", "amount": 10 + i, "at": f"2026-10-{i + 1:02d}T00:00:00Z"} for i in range(5)]
    assert client.post("/api/v1/me/deposits", json={"items": items}, headers=auth).status_code == 201
    page = client.get("/api/v1/me/deposits?limit=2", headers=auth).get_json()
    assert [d["id"] for d in page["data"]] == ["d4", "d3"]
    assert page["pagination"]["has_more"]
    nxt = page["pagination"]["next_before"]
    page2 = client.get(f"/api/v1/me/deposits?limit=2&before={nxt}", headers=auth).get_json()
    assert [d["id"] for d in page2["data"]] == ["d2", "d1"]


def test_records_are_private(client, auth):
    client.post("/api/v1/me/skip-queue", json={"id": "s1", "amount": 50, "source": "skip", "at": "2026-10-20T00:00:00Z"}, headers=auth)
    _, other = login(client, "9123456780", "Ravi")
    assert client.get("/api/v1/me/skip-queue", headers=other).get_json()["data"] == []
    assert client.get("/api/v1/me/skip-queue/s1", headers=other).status_code == 404


def test_clear_requires_confirm(client, auth):
    assert client.delete("/api/v1/me/skip-queue", headers=auth).status_code == 400
    assert client.delete("/api/v1/me/skip-queue?confirm=true", headers=auth).status_code == 200


def test_state_import_and_snapshot(client, auth):
    local = {
        "baseline": PROFILE,
        "logs": [{"id": "l1", "kind": "smoked", "count": 2, "at": "2026-10-19T09:00:00Z"}],
        "deposits": [],
        "sips": [{"id": "sp1", "metal": "gold", "amount": 500, "frequency": "weekly", "active": True, "startedAt": "2026-10-01T00:00:00Z"}],
        "purchases": [{"id": "p1", "metal": "gold", "amountInr": 100, "grams": 0.0065, "pricePerGram": 15400, "feeInr": 0, "source": "one_time", "at": "2026-10-18T00:00:00Z"}],
        "skipQueue": [{"id": "q1", "amount": 50, "source": "skip", "at": "2026-10-20T00:00:00Z"}],
        "innovations": {"city": "Mumbai", "milestonesSeen": ["first_skip"]},
        "savingsGoal": 2000,
    }
    res = client.post("/api/v1/me/state/import", json=local, headers=auth)
    assert res.status_code == 200, res.get_json()
    assert res.get_json()["data"]["imported"]["logs"] == 1
    client.post("/api/v1/me/state/import", json=local, headers=auth)  # idempotent

    state = client.get("/api/v1/me/state", headers=auth).get_json()["data"]
    assert state["profile"]["name"] == "Anya"
    assert len(state["logs"]) == 1 and len(state["sip_plans"]) == 1 and len(state["skip_queue"]) == 1
    assert state["settings"]["city"] == "Mumbai" and state["settings"]["savings_goal"] == 2000
