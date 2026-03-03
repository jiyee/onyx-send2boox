"""Project-specific exceptions."""

from __future__ import annotations

from typing import Any


class Send2BooxError(Exception):
    """Base class for all project-specific exceptions."""


class ConfigError(Send2BooxError):
    """Raised when configuration is missing or invalid."""


class ApiError(Send2BooxError):
    """Raised when the send2boox HTTP API returns an error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        payload: Any | None = None,
        url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload
        self.url = url


class AuthenticationError(ApiError):
    """Raised when authentication/token operations fail."""


class ResponseFormatError(ApiError):
    """Raised when the remote payload shape is not as expected."""


class UploadError(Send2BooxError):
    """Raised when OSS upload fails."""
