import logging

from flask import Flask, jsonify
from pydantic import ValidationError
from werkzeug.exceptions import HTTPException

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def ok(data=None, status: int = 200, **meta):
    return jsonify({"success": True, "data": data, **meta}), status


def error_response(status: int, code: str, message: str, details=None):
    body = {"success": False, "error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return error_response(e.status, e.code, e.message, e.details)

    @app.errorhandler(ValidationError)
    def _validation(e: ValidationError):
        details = [
            {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
            for err in e.errors(include_url=False)
        ]
        return error_response(422, "VALIDATION_ERROR", "Request body is invalid.", details)

    @app.errorhandler(HTTPException)
    def _http(e: HTTPException):
        code = (e.name or "HTTP_ERROR").upper().replace(" ", "_")
        return error_response(e.code or 500, code, e.description or e.name)

    @app.errorhandler(Exception)
    def _unhandled(e: Exception):
        log.exception("Unhandled error")
        return error_response(500, "INTERNAL_ERROR", "Something went wrong.")
