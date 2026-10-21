from datetime import datetime, timezone

from pymongo import UpdateOne
from pymongo.database import Database

from ..data import prices_telangana

DATASETS = {prices_telangana.STATE: prices_telangana}


def _docs(dataset) -> list[dict]:
    docs = []
    for item_id, name, category, price, pack, source, confidence in dataset.DRINKS:
        docs.append(
            {
                "item_id": item_id,
                "kind": "drink",
                "name": name,
                "category": category,
                "price": price,
                "pack_ml": pack,
                "source": source,
                "confidence": confidence,
            }
        )
    for item_id, name, tier, price, sticks, source, confidence in dataset.CIGARETTES:
        docs.append(
            {
                "item_id": item_id,
                "kind": "cigarette",
                "name": name,
                "category": tier,
                "price": price,
                "pack_size": sticks,
                "source": source,
                "confidence": confidence,
            }
        )
    return docs


def seed_prices(db: Database, state: str) -> int:
    dataset = DATASETS[state]
    now = datetime.now(timezone.utc)
    ops = []
    for doc in _docs(dataset):
        src = dataset.SOURCES[doc["source"]]
        doc |= {
            "state": state,
            "source_label": src["label"],
            "source_url": src["url"],
            "as_of": dataset.AS_OF,
            "updated_at": now,
        }
        ops.append(UpdateOne({"state": state, "item_id": doc["item_id"]}, {"$set": doc}, upsert=True))
    if ops:
        db.catalog_prices.bulk_write(ops, ordered=False)
    return len(ops)


def ensure_seeded(db: Database) -> None:
    for state in DATASETS:
        if db.catalog_prices.count_documents({"state": state}, limit=1) == 0:
            seed_prices(db, state)


def list_prices(db: Database, state: str) -> list[dict]:
    return list(
        db.catalog_prices.find({"state": state}, {"_id": 0}).sort([("kind", 1), ("category", 1), ("price", 1)])
    )
