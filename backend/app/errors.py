"""Standard error model. Every API error is {error:{kind, message, details?}}."""
from __future__ import annotations

from typing import Any

KINDS = ("quota", "blocked", "invalid", "network", "timeout", "auth", "not_found", "confirm_required", "forbidden",
         "not_configured")

HTTP_STATUS = {
    "invalid": 400,
    "auth": 401,
    "not_found": 404,
    "confirm_required": 409,
    "forbidden": 403,
    "not_configured": 400,
    "quota": 429,
    "blocked": 422,
    "network": 502,
    "timeout": 504,
}


class ApiError(Exception):
    def __init__(self, kind: str, message: str, details: Any = None, status: int | None = None):
        assert kind in KINDS, kind
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.details = details
        self.status = status or HTTP_STATUS[kind]

    def body(self) -> dict:
        err: dict[str, Any] = {"kind": self.kind, "message": self.message}
        if self.details is not None:
            err["details"] = self.details
        return {"error": err}


class AdapterError(ApiError):
    """Error normalised by an adapter to one of the standard kinds.

    `before_send=True` means the failure provably happened before the request reached the provider
    (e.g. connection refused), so repeating the submit cannot double-bill (invariant 14).
    """

    def __init__(self, kind: str, message: str, details: Any = None, status: int | None = None,
                 before_send: bool = False):
        super().__init__(kind, message, details, status)
        self.before_send = before_send
