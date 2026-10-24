"""Request models. Accept snake_case or the app's camelCase; responses are snake_case."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

Metal = Literal["gold", "silver"]
Frequency = Literal["daily", "weekly", "monthly"]


def money(**kw):
    return Field(ge=0, le=10_000_000, **kw)


def client_id():
    return Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")


def reference():
    return Field(default=None, min_length=6, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")


class Schema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
        str_strip_whitespace=True,
    )


# --- auth --------------------------------------------------------------------


class GoogleSignInIn(Schema):
    # The Google ID token (JWT) returned by the Google Sign-In SDK on the client.
    id_token: str = Field(min_length=20, max_length=4096)


class RefreshIn(Schema):
    refresh_token: str = Field(min_length=20, max_length=200)


class LogoutIn(Schema):
    refresh_token: str | None = Field(default=None, max_length=200)
    all_devices: bool = False


# --- profile & settings ------------------------------------------------------


class AccountPatch(Schema):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    email: str | None = Field(default=None, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    # 10-digit Indian mobile (OroPocket needs it for gold buy/sell). Normalized server-side.
    mobile: str | None = Field(default=None, min_length=1, max_length=20)


class Profile(Schema):
    mode: Literal["quit", "reduce"]
    name: str = Field(min_length=1, max_length=80)
    cigarettes_per_day: int = Field(ge=0, le=200)
    cost_per_cigarette: float = Field(ge=0, le=10_000)
    reduce_target_per_day: int | None = Field(default=None, ge=0, le=200)
    cigarette_brand: str | None = Field(default=None, max_length=80)
    track_drinking: bool = False
    drinks_per_day: float | None = Field(default=None, ge=0, le=100)
    cost_per_drink: float | None = Field(default=None, ge=0, le=100_000)
    drink_name: str | None = Field(default=None, max_length=80)
    cigarette_prices: dict[str, float] | None = None
    drink_prices: dict[str, float] | None = None
    started_at: datetime | None = Field(default=None, validation_alias="createdAt")

    @field_validator("cigarette_prices", "drink_prices")
    @classmethod
    def _small_maps(cls, v):
        if v is not None and len(v) > 50:
            raise ValueError("at most 50 entries")
        return v


class ProfilePatch(Profile):
    mode: Literal["quit", "reduce"] | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    cigarettes_per_day: int | None = Field(default=None, ge=0, le=200)
    cost_per_cigarette: float | None = Field(default=None, ge=0, le=10_000)
    track_drinking: bool | None = None


class SettingsPatch(Schema):
    skip_to_sip_enabled: bool | None = None
    skip_to_sip_amount: float | None = Field(default=None, ge=0, le=100_000)
    city: str | None = Field(default=None, max_length=60)
    festival_goal_id: str | None = Field(default=None, max_length=60)
    last_gold_price_seen: float | None = Field(default=None, ge=0)
    soft_reset_count: int | None = Field(default=None, ge=0)
    lifetime_avoided: float | None = money(default=None)
    lifetime_gold_inr: float | None = money(default=None)
    lifetime_skips: int | None = Field(default=None, ge=0)
    milestones_seen: list[str] | None = Field(default=None, max_length=500)
    honest_day_date: str | None = Field(default=None, max_length=10)
    savings_goal: float | None = money(default=None)
    last_check_in_date: str | None = Field(default=None, max_length=10)
    game_wins_today: int | None = Field(default=None, ge=0, le=1000)
    game_wins_date: str | None = Field(default=None, max_length=10)


DEFAULT_SETTINGS = {
    "skip_to_sip_enabled": True,
    "skip_to_sip_amount": 0,
    "city": "Bengaluru",
    "soft_reset_count": 0,
    "lifetime_avoided": 0,
    "lifetime_gold_inr": 0,
    "lifetime_skips": 0,
    "milestones_seen": [],
    "savings_goal": 0,
    "last_check_in_date": None,
}


# --- per-user records --------------------------------------------------------


class Record(Schema):
    id: str = client_id()
    at: datetime

    @field_validator("at")
    @classmethod
    def _not_far_future(cls, v: datetime):
        if v.year > 2100:
            raise ValueError("timestamp out of range")
        return v


class HabitLog(Record):
    kind: Literal["smoked", "skipped", "checkin", "drank", "skipped_drink"]
    count: int = Field(ge=0, le=200)
    note: str | None = Field(default=None, max_length=500)
    mood: Literal["steady", "craving", "strong"] | None = None
    brand: str | None = Field(default=None, max_length=80)
    urge_seconds: int | None = Field(default=None, ge=0, le=86_400)
    from_game: bool | None = None


class Deposit(Record):
    amount: float = money()
    note: str | None = Field(default=None, max_length=500)


class SkipQueueItem(Record):
    amount: float = money()
    source: Literal["skip", "urge_tax", "sponsor"]
    note: str | None = Field(default=None, max_length=500)


class Purchase(Record):
    metal: Metal
    amount_inr: float = money()
    grams: float = Field(ge=0, le=100_000)
    price_per_gram: float = Field(ge=0)
    fee_inr: float = Field(default=0, ge=0)
    source: Literal["sip", "one_time", "skip_sip", "urge_tax"]


class SipPlan(Record):
    at: datetime = Field(validation_alias="startedAt")
    metal: Metal
    amount: float = Field(ge=1, le=1_000_000)
    frequency: Frequency
    active: bool = True

    @model_validator(mode="before")
    @classmethod
    def _accept_started_at(cls, data):
        if isinstance(data, dict) and "at" in data and "startedAt" not in data:
            data = {**data, "startedAt": data["at"]}
        if isinstance(data, dict) and "started_at" in data and "startedAt" not in data:
            data = {**data, "startedAt": data["started_at"]}
        return data


class BulkIn(Schema):
    items: list[dict] = Field(min_length=1, max_length=500)


class StateImport(Schema):
    """The app's local HaloState, imported once after first login."""

    baseline: Profile | None = None
    logs: list[HabitLog] = Field(default_factory=list, max_length=20_000)
    deposits: list[Deposit] = Field(default_factory=list, max_length=5_000)
    skip_queue: list[SkipQueueItem] = Field(default_factory=list, max_length=5_000)
    purchases: list[Purchase] = Field(default_factory=list, max_length=5_000)
    sips: list[SipPlan] = Field(default_factory=list, max_length=200)
    innovations: SettingsPatch | None = None
    savings_goal: float | None = money(default=None)
    last_check_in_date: str | None = None
    game_wins_today: int | None = None
    game_wins_date: str | None = None


# --- gold ----------------------------------------------------------------------


class EmbedLaunch(Schema):
    screen: Literal[
        "buy", "sell", "sip", "sips", "kyc", "transactions", "rewards", "spin", "coin_store", "gift"
    ]
    metal: Metal | None = None
    amount: float | None = Field(default=None, gt=0, le=1_000_000)
    grams: float | None = Field(default=None, gt=0, le=100_000)
    frequency: Frequency | None = None
    goal: str | None = Field(default=None, max_length=60)
    goal_name: str | None = Field(default=None, max_length=80)


class EmbedSessionIn(Schema):
    launch: EmbedLaunch | None = None
    source: str | None = Field(default=None, max_length=40)


class TradeQuoteIn(Schema):
    asset_type: Metal
    amount_inr: float | None = Field(default=None, gt=0, le=1_000_000)
    quantity_grams: float | None = Field(default=None, gt=0, le=100_000)

    @model_validator(mode="after")
    def _one_amount(self):
        if (self.amount_inr is None) == (self.quantity_grams is None):
            raise ValueError("Provide exactly one of amount_inr or quantity_grams.")
        return self


class TradeConfirmIn(Schema):
    quote_id: str = Field(min_length=3, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")


class PaymentOrderIn(Schema):
    amount_inr: float = Field(ge=1, le=50_000)
    asset_type: Metal
    checkout_type: Literal["hosted", "intent"] = "hosted"
    return_url: str | None = Field(default=None, max_length=500)
    reference: str | None = reference()


class SipCreateIn(Schema):
    installment_amount_inr: float = Field(ge=100, le=1_000_000)
    frequency: Frequency
    asset_type: Metal
    name: str | None = Field(default=None, max_length=80)
    return_url: str | None = Field(default=None, max_length=500)
    reference: str | None = reference()
