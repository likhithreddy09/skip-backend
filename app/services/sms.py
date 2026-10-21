"""SMS delivery for login OTPs. Pick with OTP_PROVIDER = console | msg91 | twilio | disabled."""

import logging

import requests
from flask import current_app

from ..errors import ApiError

log = logging.getLogger(__name__)
TIMEOUT = 10


def send_otp_sms(mobile: str, code: str) -> None:
    provider = current_app.config["OTP_PROVIDER"]
    if provider == "disabled":
        raise ApiError(503, "OTP_DISABLED", "SMS login is not enabled on this server.")
    if provider == "console":
        log.warning("[dev OTP] +91%s → %s", mobile, code)
        return
    if provider == "msg91":
        _send_msg91(mobile, code)
        return
    if provider == "twilio":
        _send_twilio(mobile, code)
        return
    raise ApiError(500, "OTP_PROVIDER_INVALID", f"Unknown OTP_PROVIDER '{provider}'.")


def _send_msg91(mobile: str, code: str) -> None:
    cfg = current_app.config
    if not cfg["MSG91_AUTH_KEY"] or not cfg["MSG91_TEMPLATE_ID"]:
        raise ApiError(503, "OTP_PROVIDER_NOT_CONFIGURED", "MSG91 credentials are missing.")
    try:
        res = requests.post(
            "https://control.msg91.com/api/v5/otp",
            params={
                "template_id": cfg["MSG91_TEMPLATE_ID"],
                "mobile": f"91{mobile}",
                "otp": code,
            },
            headers={"authkey": cfg["MSG91_AUTH_KEY"], "Accept": "application/json"},
            timeout=TIMEOUT,
        )
        body = res.json() if res.content else {}
    except requests.RequestException as e:
        log.error("MSG91 request failed: %s", e)
        raise ApiError(502, "OTP_SEND_FAILED", "Couldn't send the OTP. Try again.")
    if res.status_code >= 400 or body.get("type") == "error":
        log.error("MSG91 rejected OTP: %s %s", res.status_code, body)
        raise ApiError(502, "OTP_SEND_FAILED", "Couldn't send the OTP. Try again.")


def _send_twilio(mobile: str, code: str) -> None:
    cfg = current_app.config
    sid, token, sender = cfg["TWILIO_ACCOUNT_SID"], cfg["TWILIO_AUTH_TOKEN"], cfg["TWILIO_FROM"]
    if not (sid and token and sender):
        raise ApiError(503, "OTP_PROVIDER_NOT_CONFIGURED", "Twilio credentials are missing.")
    try:
        res = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            data={
                "To": f"+91{mobile}",
                "From": sender,
                "Body": f"{code} is your SkipMint login code. It expires in 5 minutes.",
            },
            auth=(sid, token),
            timeout=TIMEOUT,
        )
    except requests.RequestException as e:
        log.error("Twilio request failed: %s", e)
        raise ApiError(502, "OTP_SEND_FAILED", "Couldn't send the OTP. Try again.")
    if res.status_code >= 400:
        log.error("Twilio rejected OTP: %s %s", res.status_code, res.text[:300])
        raise ApiError(502, "OTP_SEND_FAILED", "Couldn't send the OTP. Try again.")
