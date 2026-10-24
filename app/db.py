import logging

import certifi
from flask import Flask, current_app
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.database import Database

log = logging.getLogger(__name__)

# Per-user record collections exposed under /me/<resource>.
RECORD_COLLECTIONS = ("habit_logs", "deposits", "skip_queue", "purchases", "sip_plans")


def init_db(app: Flask) -> None:
    uri = app.config["MONGODB_URI"]
    if uri:
        # Atlas requires TLS. On some hosts the system CA store triggers a
        # "TLSV1_ALERT_INTERNAL_ERROR" handshake failure, so point pymongo at
        # certifi's up-to-date CA bundle explicitly.
        client = MongoClient(
            uri,
            tz_aware=True,
            serverSelectionTimeoutMS=8000,
            appname="skipmint-api",
            tlsCAFile=certifi.where(),
        )
    else:
        if app.config["IS_PRODUCTION"]:
            raise RuntimeError("MONGODB_URI is required in production")
        import mongomock

        client = mongomock.MongoClient(tz_aware=True)
        log.warning("MONGODB_URI not set — using in-memory mongomock (data is lost on restart)")

    db = client[app.config["MONGODB_DB"]]
    app.extensions["mongo_client"] = client
    app.extensions["mongo_db"] = db
    app.extensions["mongo_is_mock"] = not uri
    try:
        ensure_indexes(db)
    except Exception:
        # Don't let a transient connection/index issue crash-loop the worker and
        # keep the HTTP port closed. Indexes are idempotent and get created on a
        # later boot; the /health endpoint stays up so the platform sees the port.
        log.exception("ensure_indexes failed during startup; continuing without blocking boot")


def get_db() -> Database:
    return current_app.extensions["mongo_db"]


def ensure_indexes(db: Database) -> None:
    db.users.create_index("mobile", unique=True)

    db.otp_requests.create_index("mobile", unique=True)
    db.otp_requests.create_index("purge_at", expireAfterSeconds=0)

    db.sessions.create_index("token_hash", unique=True)
    db.sessions.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    db.sessions.create_index("expires_at", expireAfterSeconds=0)

    for name in RECORD_COLLECTIONS:
        db[name].create_index([("user_id", ASCENDING), ("client_id", ASCENDING)], unique=True)
        db[name].create_index([("user_id", ASCENDING), ("at", DESCENDING)])

    db.oro_accounts.create_index("user_id", unique=True)
    db.oro_accounts.create_index("user_codes")

    db.oro_transactions.create_index("transaction_id", unique=True)
    db.oro_transactions.create_index([("user_id", ASCENDING), ("occurred_at", DESCENDING)])

    db.oro_sips.create_index("sip_id", unique=True)
    db.oro_sips.create_index("reference")
    db.oro_sips.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])

    db.payment_orders.create_index("payment_id", unique=True)
    db.payment_orders.create_index("reference", unique=True)
    db.payment_orders.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])

    db.trade_quotes.create_index("quote_id", unique=True)
    db.trade_quotes.create_index("purge_at", expireAfterSeconds=0)

    db.webhook_events.create_index("event_id", unique=True)
    db.webhook_events.create_index([("received_at", DESCENDING)])

    db.catalog_prices.create_index([("state", ASCENDING), ("item_id", ASCENDING)], unique=True)
    db.catalog_prices.create_index([("state", ASCENDING), ("kind", ASCENDING), ("category", ASCENDING)])

    from .services.catalog_prices import ensure_seeded

    ensure_seeded(db)
