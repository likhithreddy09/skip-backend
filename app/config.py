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
        "OTP_PEPPER": os.getenv("OTP_PEPPER", ""),
        "ACCESS_TOKEN_TTL_MINUTES": _int("ACCESS_TOKEN_TTL_MINUTES", 60),
        "REFRESH_TOKEN_TTL_DAYS": _int("REFRESH_TOKEN_TTL_DAYS", 30),
        "OTP_PROVIDER": os.getenv("OTP_PROVIDER", "console").strip().lower(),
        "OTP_LENGTH": max(4, min(8, _int("OTP_LENGTH", 6))),
        "OTP_TTL_SECONDS": 300,
        "OTP_RESEND_COOLDOWN_SECONDS": 30,
        "OTP_MAX_SENDS_PER_WINDOW": 5,
        "OTP_SEND_WINDOW_SECONDS": 15 * 60,
        "OTP_MAX_ATTEMPTS": 5,
        "MSG91_AUTH_KEY": os.getenv("MSG91_AUTH_KEY", ""),
        "MSG91_TEMPLATE_ID": os.getenv("MSG91_TEMPLATE_ID", ""),
        "TWILIO_ACCOUNT_SID": os.getenv("TWILIO_ACCOUNT_SID", ""),
        "TWILIO_AUTH_TOKEN": os.getenv("TWILIO_AUTH_TOKEN", ""),
        "TWILIO_FROM": os.getenv("TWILIO_FROM", ""),
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
    for key in ("JWT_SECRET", "OTP_PEPPER"):
        if len(config[key]) < 32 or config[key] == "change-me":
            problems.append(f"{key} (32+ random chars)")
    if config["OTP_PROVIDER"] == "console":
        problems.append("OTP_PROVIDER (console is dev-only; use msg91, twilio or disabled)")
    if problems:
        raise RuntimeError("Missing/unsafe production config: " + ", ".join(problems))
