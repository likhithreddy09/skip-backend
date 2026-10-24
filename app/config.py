import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


def load_config() -> dict:
    env = os.getenv("APP_ENV", "development").strip().lower()
    oro_key = os.getenv("OROPOCKET_API_KEY", "").strip()
    return {
        "APP_ENV": env,
        "IS_PRODUCTION": env == "production",
        "MONGODB_URI": os.getenv("MONGODB_URI", "").strip(),
        "MONGODB_DB": os.getenv("MONGODB_DB", "skipmint").strip(),
        "JWT_SECRET": os.getenv("JWT_SECRET", ""),
        "ACCESS_TOKEN_TTL_MINUTES": _int("ACCESS_TOKEN_TTL_MINUTES", 60),
        "REFRESH_TOKEN_TTL_DAYS": _int("REFRESH_TOKEN_TTL_DAYS", 30),
        # Google Sign-In: comma-separated OAuth client IDs that are valid audiences
        # for the ID token (Android, iOS, and/or Web client IDs from one project).
        "GOOGLE_CLIENT_IDS": [
            c.strip() for c in os.getenv("GOOGLE_CLIENT_IDS", "").split(",") if c.strip()
        ],
        "OROPOCKET_API_KEY": oro_key,
        "OROPOCKET_BASE_URL": "https://api.oropocket.com/partner",
        "OROPOCKET_MODE": "live"
        if oro_key.startswith("oro_live_")
        else "sandbox"
        if oro_key.startswith("oro_test_")
        else "unconfigured",
        "OROPOCKET_WEBHOOK_SECRET": os.getenv("OROPOCKET_WEBHOOK_SECRET", ""),
        "ENABLE_RAW_TRADING": _bool("ENABLE_RAW_TRADING"),
        "CORS_ORIGINS": [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()],
        "RATELIMIT_STORAGE_URI": os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
        "MAX_CONTENT_LENGTH": 2 * 1024 * 1024,
    }


def validate_config(config: dict) -> None:
    if not config["IS_PRODUCTION"]:
        return
    problems = []
    if not config["MONGODB_URI"]:
        problems.append("MONGODB_URI")
    if len(config["JWT_SECRET"]) < 32 or config["JWT_SECRET"] == "change-me":
        problems.append("JWT_SECRET (32+ random chars)")
    if not config["GOOGLE_CLIENT_IDS"]:
        problems.append("GOOGLE_CLIENT_IDS (at least one Google OAuth client ID)")
    if problems:
        raise RuntimeError("Missing/unsafe production config: " + ", ".join(problems))
