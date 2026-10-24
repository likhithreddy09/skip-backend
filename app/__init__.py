import logging

from dotenv import load_dotenv
from flask import Flask
from flask_cors import CORS

from .config import load_config, validate_config
from .db import init_db
from .errors import error_response, register_error_handlers
from .extensions import limiter
from .utils import JSONProvider

API_PREFIX = "/api/v1"


def create_app(overrides: dict | None = None) -> Flask:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = Flask(__name__)
    app.json = JSONProvider(app)
    app.config.from_mapping(load_config())
    if overrides:
        app.config.update(overrides)
    validate_config(app.config)

    if not app.config["IS_PRODUCTION"]:
        # Dev-only fallback so the server boots before secrets are set.
        app.config["JWT_SECRET"] = app.config["JWT_SECRET"] or "dev-jwt-secret-change-me-0123456789"

    origins = app.config["CORS_ORIGINS"]
    CORS(app, resources={rf"{API_PREFIX}/*": {"origins": "*" if origins == ["*"] else origins}})

    app.config["RATELIMIT_HEADERS_ENABLED"] = True
    limiter.init_app(app)

    @app.errorhandler(429)
    def _rate_limited(e):
        return error_response(429, "RATE_LIMITED", "Too many requests. Slow down and retry.")

    init_db(app)
    register_error_handlers(app)

    from .routes import auth, catalog, gold, health, me, payments, webhooks

    for module in (health, auth, me, gold, payments, webhooks, catalog):
        app.register_blueprint(module.bp, url_prefix=f"{API_PREFIX}{module.bp.url_prefix or ''}")

    return app
