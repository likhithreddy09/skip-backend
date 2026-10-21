def test_prices_telangana(client):
    res = client.get("/api/v1/catalog/prices?state=telangana")
    assert res.status_code == 200
    data = res.get_json()["data"]
    assert data["state"] == "telangana"
    by_id = {i["item_id"]: i for i in data["items"]}

    stag = by_id["royal-stag"]
    assert stag["kind"] == "drink" and stag["category"] == "whisky"
    assert stag["price"] == 880 and stag["pack_ml"] == 750
    assert stag["source_label"] and stag["source_url"]

    assert by_id["glenfiddich-12"]["pack_ml"] == 700
    assert by_id["corona"]["pack_ml"] == 330

    gf = by_id["gold-flake"]
    assert gf["kind"] == "cigarette" and gf["pack_size"] == 20 and gf["price"] == 480
    assert by_id["capstan"]["confidence"] == "estimate"


def test_prices_default_state_and_unknown(client):
    assert client.get("/api/v1/catalog/prices").status_code == 200
    res = client.get("/api/v1/catalog/prices?state=atlantis")
    assert res.status_code == 404
    assert res.get_json()["error"]["code"] == "STATE_NOT_SUPPORTED"


def test_seed_is_idempotent(app):
    from app.db import get_db
    from app.services.catalog_prices import seed_prices

    with app.app_context():
        db = get_db()
        before = db.catalog_prices.count_documents({})
        seed_prices(db, "telangana")
        assert db.catalog_prices.count_documents({}) == before
