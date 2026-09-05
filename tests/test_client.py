"""Tests for HighlightlyBaseClient's request handling and error mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from pyhighlightly.client import HighlightlyBaseClient
from pyhighlightly.exceptions import (
    HighlightlyAPIError,
    HighlightlyAuthError,
    HighlightlyNotFoundError,
    HighlightlyRateLimitError,
)

BASE_URL = "https://example.test"


def make_client() -> HighlightlyBaseClient:
    return HighlightlyBaseClient(api_key="test-key", base_url=BASE_URL)


@respx.mock
def test_successful_request_parses_rate_limit_headers() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={
                "x-ratelimit-requests-limit": "1000",
                "x-ratelimit-requests-remaining": "999",
            },
        )
    )
    client = make_client()

    assert client.requests_limit is None
    assert client.requests_remaining is None

    response = client._request("GET", "/teams")

    assert route.called
    assert route.calls.last.request.headers["x-rapidapi-key"] == "test-key"
    assert response.json() == {"ok": True}
    assert client.requests_limit == 1000
    assert client.requests_remaining == 999


@respx.mock
def test_401_raises_auth_error() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(401, json={"message": "invalid key"})
    )
    client = make_client()

    with pytest.raises(HighlightlyAuthError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.status_code == 401


@respx.mock
def test_403_raises_auth_error() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(403, json={"message": "forbidden"})
    )
    client = make_client()

    with pytest.raises(HighlightlyAuthError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.status_code == 403


@respx.mock
def test_404_raises_not_found_error() -> None:
    respx.get(f"{BASE_URL}/teams/1").mock(
        return_value=httpx.Response(404, json={"message": "missing"})
    )
    client = make_client()

    with pytest.raises(HighlightlyNotFoundError):
        client._request("GET", "/teams/1")


@respx.mock
def test_429_raises_rate_limit_error_with_remaining_zero() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            429,
            json={"message": "slow down"},
            headers={
                "x-ratelimit-requests-limit": "1000",
                "x-ratelimit-requests-remaining": "0",
                "retry-after": "30",
            },
        )
    )
    client = make_client()

    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.requests_remaining == 0
    assert exc_info.value.retry_after == 30


@respx.mock
def test_generic_500_raises_api_error_with_status_and_body() -> None:
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(500, text="internal error"))
    client = make_client()

    with pytest.raises(HighlightlyAPIError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.status_code == 500
    assert exc_info.value.response_body == "internal error"


@respx.mock
def test_missing_rate_limit_headers_do_not_crash() -> None:
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json={"ok": True}))
    client = make_client()

    client._request("GET", "/teams")

    assert client.requests_limit is None
    assert client.requests_remaining is None


@respx.mock
def test_malformed_rate_limit_headers_do_not_crash() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={
                "x-ratelimit-requests-limit": "not-a-number",
                "x-ratelimit-requests-remaining": "also-not-a-number",
            },
        )
    )
    client = make_client()

    client._request("GET", "/teams")

    assert client.requests_limit is None
    assert client.requests_remaining is None


@respx.mock
def test_zero_remaining_preempts_further_requests_locally() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"x-ratelimit-requests-remaining": "0"},
        )
    )
    client = make_client()

    client._request("GET", "/teams")
    assert client.requests_remaining == 0

    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.requests_remaining == 0
