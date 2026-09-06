"""Tests for HighlightlyBaseClient's request handling and error mapping."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from pydantic import BaseModel, ValidationError

from pyhighlightly.client import HighlightlyBaseClient
from pyhighlightly.exceptions import (
    _RESPONSE_BODY_TRUNCATE_AT,
    HighlightlyAPIError,
    HighlightlyAuthError,
    HighlightlyNotFoundError,
    HighlightlyRateLimitError,
    HighlightlyResponseError,
)
from pyhighlightly.models.common import PaginatedResponse, Pagination, Plan
from pyhighlightly.nfl import NFLClient

BASE_URL = "https://example.test"
NFL_BASE_URL = "https://american-football.highlightly.net"


def make_client() -> HighlightlyBaseClient:
    return HighlightlyBaseClient(api_key="test-key", base_url=BASE_URL)


# -- constructor validation --


def test_empty_api_key_raises_value_error() -> None:
    with pytest.raises(ValueError, match="api_key is required"):
        HighlightlyBaseClient(api_key="", base_url=BASE_URL)


def test_missing_base_url_raises_value_error() -> None:
    # HighlightlyBaseClient has no base_url class attribute of its own
    # (subclasses like AmericanFootballClient set one), so instantiating
    # it directly with neither a constructor argument nor a subclass
    # default should fail.
    with pytest.raises(ValueError) as exc_info:
        HighlightlyBaseClient(api_key="test-key")

    # The message carries real information -- both ways to satisfy it --
    # so pin both, not just that some ValueError was raised.
    message = str(exc_info.value)
    assert "base_url must be provided" in message
    assert "constructor argument" in message
    assert "class attribute on a subclass" in message


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
    assert exc_info.value.url == f"{BASE_URL}/teams"
    assert exc_info.value.response_body == '{"message":"invalid key"}'


@respx.mock
def test_403_raises_auth_error() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(403, json={"message": "forbidden"})
    )
    client = make_client()

    with pytest.raises(HighlightlyAuthError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.status_code == 403
    assert exc_info.value.url == f"{BASE_URL}/teams"
    assert exc_info.value.response_body == '{"message":"forbidden"}'


@respx.mock
def test_404_raises_not_found_error() -> None:
    respx.get(f"{BASE_URL}/teams/1").mock(
        return_value=httpx.Response(404, json={"message": "missing"})
    )
    client = make_client()

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client._request("GET", "/teams/1")

    # status_code defaults to 404 on the exception, but raise_for_response
    # should still pass it explicitly for this, its one real trigger --
    # this is the same value either way, so this pins the call site, not
    # just the default.
    assert exc_info.value.status_code == 404
    assert exc_info.value.url == f"{BASE_URL}/teams/1"
    assert exc_info.value.response_body == '{"message":"missing"}'


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
    # A real 429 response, not local preemption: status_code is the actual
    # status, preempted is False, and retry_at (preemption-only) is unset.
    assert exc_info.value.status_code == 429
    assert exc_info.value.url == f"{BASE_URL}/teams"
    assert exc_info.value.response_body == '{"message":"slow down"}'
    assert exc_info.value.preempted is False
    assert exc_info.value.retry_at is None


@respx.mock
def test_429_with_no_retry_after_header_does_not_crash() -> None:
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            429,
            json={"message": "slow down"},
            headers={"x-ratelimit-requests-remaining": "0"},
        )
    )
    client = make_client()

    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.retry_after is None


@respx.mock
def test_429_with_http_date_retry_after_degrades_to_none() -> None:
    # RFC 9110 permits retry-after as either a number of seconds or an
    # HTTP-date; float() can't parse the latter. _parse_float_header should
    # degrade to None rather than let a raw ValueError escape.
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(
            429,
            json={"message": "slow down"},
            headers={
                "x-ratelimit-requests-remaining": "0",
                "retry-after": "Wed, 21 Oct 2015 07:28:00 GMT",
            },
        )
    )
    client = make_client()

    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.retry_after is None


@respx.mock
def test_generic_500_raises_api_error_with_status_and_body() -> None:
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(500, text="internal error"))
    client = make_client()

    with pytest.raises(HighlightlyAPIError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.status_code == 500
    assert exc_info.value.response_body == "internal error"
    assert exc_info.value.url == f"{BASE_URL}/teams"


@respx.mock
def test_long_response_body_is_truncated_with_elision_marker() -> None:
    huge_body = "x" * (_RESPONSE_BODY_TRUNCATE_AT + 500)
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(500, text=huge_body))
    client = make_client()

    with pytest.raises(HighlightlyAPIError) as exc_info:
        client._request("GET", "/teams")

    body = exc_info.value.response_body
    assert body is not None
    assert len(body) < len(huge_body)
    assert body.startswith("x" * _RESPONSE_BODY_TRUNCATE_AT)
    assert body.endswith(f"...[truncated, {len(huge_body)} bytes total]")


# -- _parse_response: schema drift / non-JSON responses --


class _StrictItem(BaseModel):
    id: int
    name: str


@respx.mock
def test_schema_drift_raises_response_error_with_validation_error_chained() -> None:
    # "name" is required but missing -- a realistic API schema-drift case.
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json={"id": 1}))
    client = make_client()

    with pytest.raises(HighlightlyResponseError) as exc_info:
        client._cached_request(
            "get_thing",
            "GET",
            "/teams",
            {},
            lambda response: _StrictItem.model_validate(response.json()),
        )

    assert exc_info.value.status_code == 200
    assert exc_info.value.url == f"{BASE_URL}/teams"
    assert isinstance(exc_info.value.__cause__, ValidationError)


@respx.mock
def test_non_json_200_raises_response_error_with_json_decode_error_chained() -> None:
    # A 200 with a non-JSON body -- e.g. an HTML maintenance page served
    # without the API actually returning an error status.
    respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(200, text="<html>maintenance</html>")
    )
    client = make_client()

    with pytest.raises(HighlightlyResponseError) as exc_info:
        client._cached_request(
            "get_thing",
            "GET",
            "/teams",
            {},
            lambda response: response.json(),
        )

    assert exc_info.value.status_code == 200
    assert exc_info.value.url == f"{BASE_URL}/teams"
    assert exc_info.value.response_body == "<html>maintenance</html>"
    assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@respx.mock
def test_highlightly_error_raised_by_parse_is_not_wrapped() -> None:
    # A HighlightlyError parse() raises on purpose (e.g. the empty-array
    # guards in AmericanFootballClient) should pass through _parse_response
    # unchanged, not get reclassified as a HighlightlyResponseError.
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[]))
    client = make_client()

    def parse(response: httpx.Response) -> None:
        raise HighlightlyNotFoundError("deliberately raised by parse()")

    with pytest.raises(HighlightlyNotFoundError, match="deliberately raised by parse"):
        client._cached_request("get_thing", "GET", "/teams", {}, parse)


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
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    client._now = lambda: t0  # type: ignore[method-assign]

    client._request("GET", "/teams")
    assert client.requests_remaining == 0

    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.requests_remaining == 0
    # Preempted locally, not a real response: no status code (no request
    # was sent), preempted is True, url still says which call was blocked,
    # and retry_at is exactly the 24-hour resync window from the zero
    # that's actually being enforced -- see _preemption_retry_at.
    assert exc_info.value.status_code is None
    assert exc_info.value.preempted is True
    assert exc_info.value.url == f"{BASE_URL}/teams"
    assert exc_info.value.retry_at == t0 + timedelta(hours=24)


def test_preemption_with_no_recorded_zero_observation_has_no_retry_at() -> None:
    # The defensive edge case noted on _should_preempt_for_rate_limit: a
    # zero with no observation timestamp at all shouldn't normally happen,
    # but if it does, there's nothing to compute a resync time from.
    client = make_client()
    client._requests_remaining = 0
    assert client._zero_observed_at is None

    with pytest.raises(HighlightlyRateLimitError) as exc_info:
        client._request("GET", "/teams")

    assert exc_info.value.preempted is True
    assert exc_info.value.retry_at is None


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


def test_paginate_returns_empty_iterator_for_a_zero_result_first_page() -> None:
    # A routine, realistic response -- a filter that matches nothing --
    # not an error case. `not page.data` should return cleanly rather than
    # raising or yielding anything.
    def fetch_fn(offset: int = 0, **kwargs: object) -> PaginatedResponse[_Item]:
        return _page([], total_count=0, offset=0)

    client = make_client()
    items = list(client.paginate(fetch_fn))

    assert items == []


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


def test_request_after_close_fails_the_way_a_closed_httpx_client_would() -> None:
    # Distinct from the is_closed check above: this confirms the actual
    # behavioral consequence of closing -- a real request attempted
    # afterwards -- propagates cleanly rather than hanging, silently
    # no-op'ing, or getting masked by something in _request.
    client = make_client()
    client.close()

    with pytest.raises(RuntimeError, match="client has been closed"):
        client._request("GET", "/teams")


def test_with_block_closes_client_on_exit_even_if_the_block_raises() -> None:
    client = make_client()

    with pytest.raises(ValueError, match="boom"), client:
        assert client._client.is_closed is False
        raise ValueError("boom")

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
