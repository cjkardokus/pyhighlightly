"""Generic, sport-agnostic HTTP client for the Highlightly API family.

``HighlightlyBaseClient`` knows nothing about American football, basketball,
soccer, or any other sport -- it only knows how to authenticate, make a
request against a Highlightly API host, and turn the response into either
data or the right exception. Sport-specific clients (see
``pyhighlightly.american_football``) subclass it to add their own base URL
and, eventually, endpoint methods.

Request-building and response-parsing are kept as plain functions, separate
from the actual httpx call, so an ``AsyncHighlightlyBaseClient`` built on
``httpx.AsyncClient`` can reuse this logic later without duplicating it.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Any

import httpx

from pyhighlightly.exceptions import (
    HighlightlyAPIError,
    HighlightlyAuthError,
    HighlightlyNotFoundError,
    HighlightlyRateLimitError,
)

DEFAULT_TIMEOUT = 10.0

_RATE_LIMIT_HEADER = "x-ratelimit-requests-limit"
_RATE_REMAINING_HEADER = "x-ratelimit-requests-remaining"


@dataclass(frozen=True)
class PreparedRequest:
    """The pieces of one API call, resolved independent of any HTTP client."""

    method: str
    url: str
    headers: dict[str, str]
    params: dict[str, Any] | None


@dataclass(frozen=True)
class RateLimitInfo:
    """Rate-limit figures parsed from an API response's headers."""

    requests_limit: int | None
    requests_remaining: int | None


def build_request(
    *,
    method: str,
    base_url: str,
    path: str,
    api_key: str,
    params: dict[str, Any] | None,
) -> PreparedRequest:
    """Build the method/url/headers/params for a request, without sending it."""
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {"x-rapidapi-key": api_key}
    return PreparedRequest(method=method, url=url, headers=headers, params=params)


def _parse_int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_float_header(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_rate_limit_headers(headers: httpx.Headers) -> RateLimitInfo:
    """Pull the rate-limit figures out of a response's headers.

    Missing or malformed headers resolve to ``None`` rather than raising.
    """
    return RateLimitInfo(
        requests_limit=_parse_int_header(headers.get(_RATE_LIMIT_HEADER)),
        requests_remaining=_parse_int_header(headers.get(_RATE_REMAINING_HEADER)),
    )


def raise_for_response(response: httpx.Response, rate_limit: RateLimitInfo) -> None:
    """Raise the appropriate ``HighlightlyError`` subclass for an error response.

    Returns ``None`` (does nothing) for a successful response.
    """
    status = response.status_code
    if status in (401, 403):
        raise HighlightlyAuthError(
            f"Authentication failed with status {status}", status_code=status
        )
    if status == 404:
        raise HighlightlyNotFoundError(f"Resource not found: {response.request.url}")
    if status == 429:
        raise HighlightlyRateLimitError(
            "Rate limit exceeded",
            retry_after=_parse_float_header(response.headers.get("retry-after")),
            requests_remaining=rate_limit.requests_remaining,
        )
    if status >= 400:
        raise HighlightlyAPIError(
            f"Highlightly API error: {status}",
            status_code=status,
            response_body=response.text,
        )


class HighlightlyBaseClient:
    """Fully generic Highlightly API client.

    This is a public extension point: any future Highlightly sport client
    (basketball, soccer, hockey, ...) is expected to subclass this rather
    than reimplementing request handling. Subclasses typically set the
    ``base_url`` class attribute to their sport's API host.
    """

    base_url: str | None = None

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")

        resolved_base_url = base_url or self.base_url
        if not resolved_base_url:
            raise ValueError(
                "base_url must be provided, either as a constructor argument "
                "or as a class attribute on a subclass"
            )

        self._api_key = api_key
        self.base_url = resolved_base_url
        self._timeout = timeout
        self._client = httpx.Client(timeout=timeout)
        self._requests_limit: int | None = None
        self._requests_remaining: int | None = None

    @property
    def requests_limit(self) -> int | None:
        """Total requests allowed per the API's rate-limit window.

        ``None`` until the first request has been made, or if the API
        response didn't include the header.
        """
        return self._requests_limit

    @property
    def requests_remaining(self) -> int | None:
        """Requests remaining in the current rate-limit window.

        ``None`` until the first request has been made, or if the API
        response didn't include the header.
        """
        return self._requests_remaining

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        self._client.close()

    def __enter__(self) -> HighlightlyBaseClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Make an authenticated request and return the raw response.

        Raises a ``HighlightlyError`` subclass (see ``exceptions.py``) if the
        API returns an error status, or if a previous response already
        reported the rate-limit budget as exhausted.
        """
        if self._requests_remaining == 0:
            raise HighlightlyRateLimitError(
                "Rate limit budget exhausted; refusing to make a new request",
                requests_remaining=0,
            )

        prepared = build_request(
            method=method,
            base_url=self.base_url,  # type: ignore[arg-type]  # resolved non-None in __init__
            path=path,
            api_key=self._api_key,
            params=params,
        )
        response = self._client.request(
            prepared.method,
            prepared.url,
            headers=prepared.headers,
            params=prepared.params,
        )

        rate_limit = parse_rate_limit_headers(response.headers)
        self._requests_limit = rate_limit.requests_limit
        self._requests_remaining = rate_limit.requests_remaining

        raise_for_response(response, rate_limit)
        return response
