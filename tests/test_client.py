"""Tests for HighlightlyBaseClient's request handling and error mapping."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from pydantic import BaseModel

from pyhighlightly.client import HighlightlyBaseClient
from pyhighlightly.exceptions import (
    HighlightlyAPIError,
    HighlightlyAuthError,
    HighlightlyNotFoundError,
    HighlightlyRateLimitError,
)
from pyhighlightly.models.common import PaginatedResponse, Pagination, Plan
from pyhighlightly.nfl import NFLClient

BASE_URL = "https://example.test"
NFL_BASE_URL = "https://american-football.highlightly.net"


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


# -- Stale-zero re-sync (no reset-time header is available from Highlightly;
# -- see the rate-limiting note on HighlightlyBaseClient) --


@respx.mock
def test_still_preempts_within_the_24_hour_resync_window() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"x-ratelimit-requests-remaining": "0"},
        )
    )
    client = make_client()
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    client._now = lambda: t0  # type: ignore[method-assign]

    client._request("GET", "/teams")
    assert client._zero_observed_at == t0

    client._now = lambda: t0 + timedelta(hours=23)  # type: ignore[method-assign]
    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.requests_remaining == 0


@respx.mock
def test_resyncs_after_24_hours_and_allows_a_real_request_through() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"x-ratelimit-requests-remaining": "0"},
        )
    )
    client = make_client()
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    client._now = lambda: t0  # type: ignore[method-assign]

    client._request("GET", "/teams")
    assert route.call_count == 1

    # More than 24 hours later: the locally-observed zero is no longer
    # trusted, so this should hit the network again instead of preempting.
    client._now = lambda: t0 + timedelta(hours=24, minutes=1)  # type: ignore[method-assign]
    response = client._request("GET", "/teams")

    assert route.call_count == 2
    assert response.json() == {"ok": True}


@respx.mock
def test_immediate_zero_again_after_resync_restarts_the_window() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True},
            headers={"x-ratelimit-requests-remaining": "0"},
        )
    )
    client = make_client()
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    client._now = lambda: t0  # type: ignore[method-assign]
    client._request("GET", "/teams")
    assert client._zero_observed_at == t0

    # Re-sync fires and the quota is still reported as 0 -- the window
    # should restart from this new observation, not the original one.
    t1 = t0 + timedelta(hours=25)
    client._now = lambda: t1  # type: ignore[method-assign]
    client._request("GET", "/teams")
    assert client._zero_observed_at == t1

    client._now = lambda: t1 + timedelta(hours=1)  # type: ignore[method-assign]
    with pytest.raises(HighlightlyRateLimitError):
        client._request("GET", "/teams")


@respx.mock
def test_remaining_above_zero_clears_the_zero_observation() -> None:
    route = respx.get(f"{BASE_URL}/teams")
    route.side_effect = [
        httpx.Response(200, json={"ok": True}, headers={"x-ratelimit-requests-remaining": "0"}),
        httpx.Response(200, json={"ok": True}, headers={"x-ratelimit-requests-remaining": "5"}),
    ]
    client = make_client()
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    client._now = lambda: t0  # type: ignore[method-assign]

    client._request("GET", "/teams")
    assert client._zero_observed_at == t0

    # Only once the re-sync window has elapsed does a real call go through
    # again -- that's when a change in the server's reported quota can
    # actually be observed.
    client._now = lambda: t0 + timedelta(hours=25)  # type: ignore[method-assign]
    client._request("GET", "/teams")
    assert client._zero_observed_at is None
    assert client.requests_remaining == 5


# -- paginate() --


class _Item(BaseModel):
    id: int


def _page(items: list[int], total_count: int, offset: int) -> PaginatedResponse[_Item]:
    return PaginatedResponse[_Item](
        data=[_Item(id=i) for i in items],
        pagination=Pagination(totalCount=total_count, offset=offset, limit=2),
        plan=Plan(tier="BASIC", message="Some results might be hidden with FREE tier"),
    )


def test_paginate_yields_items_across_pages_and_stops_at_total_count() -> None:
    pages = {
        0: _page([1, 2], total_count=5, offset=0),
        2: _page([3, 4], total_count=5, offset=2),
        4: _page([5], total_count=5, offset=4),
    }
    calls: list[int] = []

    def fetch_fn(offset: int = 0, **kwargs: object) -> PaginatedResponse[_Item]:
        calls.append(offset)
        return pages[offset]

    client = make_client()
    items = list(client.paginate(fetch_fn))

    assert [item.id for item in items] == [1, 2, 3, 4, 5]
    assert calls == [0, 2, 4]


def test_paginate_respects_max_requests() -> None:
    pages = {
        0: _page([1, 2], total_count=100, offset=0),
        2: _page([3, 4], total_count=100, offset=2),
        4: _page([5, 6], total_count=100, offset=4),
    }
    calls: list[int] = []

    def fetch_fn(offset: int = 0, **kwargs: object) -> PaginatedResponse[_Item]:
        calls.append(offset)
        return pages[offset]

    client = make_client()
    items = list(client.paginate(fetch_fn, max_requests=2))

    assert [item.id for item in items] == [1, 2, 3, 4]
    assert calls == [0, 2]


def test_paginate_is_lazy() -> None:
    pages = {
        0: _page([1, 2], total_count=4, offset=0),
        2: _page([3, 4], total_count=4, offset=2),
    }
    calls: list[int] = []

    def fetch_fn(offset: int = 0, **kwargs: object) -> PaginatedResponse[_Item]:
        calls.append(offset)
        return pages[offset]

    client = make_client()
    generator = client.paginate(fetch_fn)

    assert calls == []  # nothing fetched until the generator is iterated

    assert next(generator).id == 1
    assert calls == [0]  # only page 1 fetched so far

    assert next(generator).id == 2
    assert calls == [0]  # page 1's items aren't exhausted yet -- no 2nd fetch

    assert next(generator).id == 3
    assert calls == [0, 2]  # page 1 exhausted -- page 2 fetched on demand


# -- context manager / close() --


def test_close_closes_the_underlying_http_client() -> None:
    client = make_client()
    assert client._client.is_closed is False

    client.close()

    assert client._client.is_closed is True


@respx.mock
def test_with_block_preserves_subclass_type_for_endpoint_methods() -> None:
    # Regression test: __enter__ used to be annotated to return
    # HighlightlyBaseClient outright, which meant `with NFLClient(...) as c:
    # c.get_teams()` failed mypy -- `c` had no endpoint methods as far as
    # the type checker was concerned, even though it obviously does at
    # runtime. The real value of this test is being type-checked by mypy
    # (tests/ is included under strict mode -- see pyproject.toml's `files`
    # setting): if __enter__'s return type ever regresses to the base
    # class, the `c.get_teams()` call below stops type-checking and
    # `uv run mypy .` fails, even though the runtime assertions here would
    # still pass regardless.
    respx.get(f"{NFL_BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[]))

    with NFLClient(api_key="test-key") as c:
        teams = c.get_teams()
        assert c._client.is_closed is False

    assert teams == []
    assert c._client.is_closed is True
