"""Exception types raised by the pyhighlightly client.

These are sport-agnostic: they're raised by ``HighlightlyBaseClient`` and
therefore apply to every Highlightly sport client built on top of it.
"""

from __future__ import annotations


class HighlightlyError(Exception):
    """Base class for all errors raised by pyhighlightly."""


class HighlightlyAuthError(HighlightlyError):
    """Raised when the API rejects the request's credentials (401/403)."""

    def __init__(self, message: str, *, status_code: int) -> None:
        """``status_code`` is the actual 401/403 status the API returned."""
        super().__init__(message)
        self.status_code = status_code


class HighlightlyNotFoundError(HighlightlyError):
    """Raised when the requested resource does not exist (404)."""

    def __init__(self, message: str, *, status_code: int = 404) -> None:
        """``status_code`` defaults to 404 -- there's no other status this is raised for."""
        super().__init__(message)
        self.status_code = status_code


class HighlightlyRateLimitError(HighlightlyError):
    """Raised when the API rate limit has been (or was already) hit.

    This covers both an explicit 429 response from the API, and the client
    proactively refusing to make a new request because a previous response
    reported ``requests_remaining == 0``.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        requests_remaining: int | None = None,
    ) -> None:
        """Both fields are ``None`` when the API response didn't include them
        (or when preempted locally without a network call at all)."""
        super().__init__(message)
        self.retry_after = retry_after
        self.requests_remaining = requests_remaining


class HighlightlyAPIError(HighlightlyError):
    """Catch-all for other 4xx/5xx responses from the API.

    Carries the raw status code and response body to aid debugging.
    """

    def __init__(self, message: str, *, status_code: int, response_body: str) -> None:
        """``response_body`` is the raw, unparsed response text."""
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
