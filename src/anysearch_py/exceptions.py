"""Exception hierarchy for AnySearch clients."""

from __future__ import annotations

from typing import Any


class AnySearchError(Exception):
    """Base class for all package-specific errors."""


class TransportError(AnySearchError):
    """Raised when the HTTP client cannot complete a request."""

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.__cause__ = cause


class ResponseDecodeError(AnySearchError):
    """Raised when a response cannot be decoded as JSON."""

    def __init__(self, message: str, *, raw: Any = None) -> None:
        super().__init__(message)
        self.raw = raw


class ResponseValidationError(AnySearchError):
    """Raised when a decoded response does not match the expected schema."""

    def __init__(self, message: str, *, payload: Any = None) -> None:
        super().__init__(message)
        self.payload = payload


class APIError(AnySearchError):
    """Raised when AnySearch returns an application-level error."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: int | str | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.error_code = error_code
        self.request_id = request_id
        self.data = data
        self.headers = headers or {}


class HTTPStatusError(APIError):
    """Raised for non-2xx HTTP responses."""


class JSONRPCError(APIError):
    """Raised for JSON-RPC error objects or MCP tool failures."""
