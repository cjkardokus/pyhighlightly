"""Tests for pyhighlightly's caching layer: InMemoryCache, cache key
construction, and HighlightlyBaseClient's TTL/enable_cache/force_refresh
wiring.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx
import respx

from pyhighlightly.american_football import AmericanFootballClient
from pyhighlightly.cache import CacheBackend, InMemoryCache
from pyhighlightly.nfl import NFLClient

BASE_URL = "https://american-football.highlightly.net"

_TEAM = {
    "id": 1,
    "logo": "https://example.com/logos/team/111.png",
    "name": "Saints",
    "displayName": "New Orleans Saints",
    "abbreviation": "NO",
    "league": "NFL",
}

_MATCH = {
    "id": 1,
    "round": "Regular Season - 32",
    "date": "2023-05-20T15:30:00.000Z",
    "league": "NFL",
    "season": 2023,
    "awayTeam": {k: v for k, v in _TEAM.items() if k != "league"},
    "homeTeam": {k: v for k, v in _TEAM.items() if k != "league"},
    "state": {
        "period": 2,
        "clock": 8,
        "description": "In progress",
        "score": {
            "current": "21 - 7",
            "firstPeriod": "0 - 0",
            "secondPeriod": "7 - 7",
            "thirdPeriod": "7 - 0",
            "fourthPeriod": "7 - 0",
            "firstOvertimePeriod": "7 - 0",
            "secondOvertimePeriod": "7 - 0",
        },
        "report": "Final",
    },
}


def _paginated(data: list[object]) -> dict[str, object]:
    return {
        "data": data,
        "pagination": {"totalCount": len(data), "offset": 0, "limit": 100},
        "plan": {"tier": "BASIC", "message": "Some results might be hidden with FREE tier"},
    }


# -- InMemoryCache --


def test_in_memory_cache_set_get_roundtrip() -> None:
    cache = InMemoryCache(now_fn=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc))
    cache.set("key", {"value": 1}, ttl_seconds=60)
    assert cache.get("key") == {"value": 1}


def test_in_memory_cache_entry_expires_after_ttl() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    now = t0
    cache = InMemoryCache(now_fn=lambda: now)

    cache.set("key", "value", ttl_seconds=60)
    assert cache.get("key") == "value"

    now = t0 + timedelta(seconds=61)
    assert cache.get("key") is None


def test_in_memory_cache_concurrent_get_on_expired_key_does_not_raise() -> None:
    # Regression test: get() used to evict an expired entry with a bare
    # `del self._entries[key]`. When multiple threads all found the same
    # entry expired at once, only the first `del` succeeded -- every other
    # thread's `del` raised KeyError, which escaped get() uncaught.
    #
    # A plain dict check-then-delete is fast enough that, on its own, real
    # threads rarely land inside that window together -- so `now_fn` sleeps
    # for a moment on every call. `time.sleep` releases the GIL, so this
    # widens the window between "found this entry expired" and "evict it"
    # enough that many real threads reliably pile up inside it at once,
    # which is what actually reproduces the race. Asserting on
    # `future.result()` re-raises any exception a thread hit as a test
    # failure instead of letting the test pass silently around it.
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    now = t0

    def now_fn() -> datetime:
        time.sleep(0.01)
        return now

    cache = InMemoryCache(now_fn=now_fn)
    cache.set("key", "value", ttl_seconds=60)
    now = t0 + timedelta(seconds=61)  # expired for every thread from here on

    thread_count = 32
    barrier = threading.Barrier(thread_count)

    def call_get() -> object:
        barrier.wait()  # release all threads into get() at the same instant
        return cache.get("key")

    with ThreadPoolExecutor(max_workers=thread_count) as executor:
        futures = [executor.submit(call_get) for _ in range(thread_count)]
        results = [future.result() for future in futures]

    assert results == [None] * thread_count


def test_in_memory_cache_delete_removes_entry() -> None:
    cache = InMemoryCache(now_fn=lambda: datetime(2024, 1, 1, tzinfo=timezone.utc))
    cache.set("key", "value", ttl_seconds=60)

    cache.delete("key")

    assert cache.get("key") is None


def test_in_memory_cache_get_missing_key_returns_none() -> None:
    cache = InMemoryCache()
    assert cache.get("nope") is None


def test_in_memory_cache_delete_missing_key_does_not_raise() -> None:
    cache = InMemoryCache()
    cache.delete("nope")  # should not raise


def test_in_memory_cache_satisfies_cache_backend_protocol() -> None:
    assert isinstance(InMemoryCache(), CacheBackend)


# -- cache key construction --


def test_cache_key_is_stable_regardless_of_param_order() -> None:
    client = AmericanFootballClient(api_key="test-key")
    key_a = client._build_cache_key("get_matches", "/matches", {"league": "NFL", "season": 2024})
    key_b = client._build_cache_key("get_matches", "/matches", {"season": 2024, "league": "NFL"})
    assert key_a == key_b


def test_cache_key_differs_for_different_params() -> None:
    client = AmericanFootballClient(api_key="test-key")
    key_a = client._build_cache_key("get_matches", "/matches", {"season": 2024})
    key_b = client._build_cache_key("get_matches", "/matches", {"season": 2025})
    assert key_a != key_b


def test_cache_key_differs_for_different_paths_with_identical_params() -> None:
    # e.g. get_team(5) vs get_team(7): no query params distinguish them, so
    # the path itself must be part of the key or they'd collide.
    client = AmericanFootballClient(api_key="test-key")
    key_a = client._build_cache_key("get_team", "/teams/5", {})
    key_b = client._build_cache_key("get_team", "/teams/7", {})
    assert key_a != key_b


# -- caching in the request flow --


@respx.mock
def test_cached_endpoint_serves_second_call_from_cache_within_ttl() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    first = client.get_teams()
    second = client.get_teams()

    assert route.call_count == 1
    assert first == second


@respx.mock
def test_cached_endpoint_refetches_after_ttl_expiry() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    now = t0
    client = AmericanFootballClient(api_key="test-key")
    # InMemoryCache uses the real clock by default; swap in a controllable
    # one so the TTL boundary can be crossed deterministically.
    client._cache = InMemoryCache(now_fn=lambda: now)

    client.get_teams()
    assert route.call_count == 1

    # get_teams' default TTL is 6 hours (21600s); jump past it.
    now = t0 + timedelta(hours=6, seconds=1)
    client.get_teams()

    assert route.call_count == 2


@respx.mock
def test_always_live_endpoint_never_serves_from_cache() -> None:
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_matches(season=2024)
    client.get_matches(season=2024)

    assert route.call_count == 2


@respx.mock
def test_force_refresh_bypasses_cache_and_refetches() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    client.get_teams()
    client.get_teams(force_refresh=True)

    assert route.call_count == 2


@respx.mock
def test_force_refresh_writes_result_back_to_cache() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    client.get_teams()
    client.get_teams(force_refresh=True)
    client.get_teams()  # should be served from the refreshed cache entry

    assert route.call_count == 2


@respx.mock
def test_enable_cache_false_disables_caching_globally() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key", enable_cache=False)

    client.get_teams()
    client.get_teams()

    assert route.call_count == 2


@respx.mock
def test_cache_ttls_override_changes_only_that_endpoint() -> None:
    standings_route = respx.get(f"{BASE_URL}/standings").mock(
        return_value=httpx.Response(
            200,
            json=_paginated(
                [
                    {
                        "leagueName": "AFC",
                        "abbreviation": "AFC",
                        "year": 2024,
                        "leagueType": "NFL",
                        "seasonType": "Preseason",
                        "startDate": "2024-08-01T07:00:00.000Z",
                        "endDate": "2024-09-05T06:59:00.000Z",
                        "data": [],
                    }
                ]
            ),
        )
    )
    teams_route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(200, json=[_TEAM])
    )

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    now = t0
    client = AmericanFootballClient(api_key="test-key", cache_ttls={"get_standings": 60})
    client._cache = InMemoryCache(now_fn=lambda: now)

    client.get_standings(year=2024)
    client.get_teams()

    now = t0 + timedelta(seconds=61)

    client.get_standings(year=2024)  # override TTL (60s) has elapsed -> refetch
    client.get_teams()  # default TTL (6h) has not elapsed -> still cached

    assert standings_route.call_count == 2
    assert teams_route.call_count == 1


@respx.mock
def test_custom_cache_backend_is_used_when_provided() -> None:
    class _RecordingCache:
        """A minimal CacheBackend implementation, not InMemoryCache, to
        confirm the Protocol-based extension point actually works for a
        non-default backend."""

        def __init__(self) -> None:
            self.store: dict[str, object] = {}
            self.get_calls: list[str] = []
            self.set_calls: list[tuple[str, object, int]] = []

        def get(self, key: str) -> object | None:
            self.get_calls.append(key)
            return self.store.get(key)

        def set(self, key: str, value: object, ttl_seconds: int) -> None:
            self.set_calls.append((key, value, ttl_seconds))
            self.store[key] = value

        def delete(self, key: str) -> None:
            self.store.pop(key, None)

    custom_cache = _RecordingCache()
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key", cache=custom_cache)

    first = client.get_teams()
    second = client.get_teams()

    assert route.call_count == 1
    assert first == second
    assert len(custom_cache.set_calls) == 1
    assert custom_cache.set_calls[0][2] == 21600
    assert len(custom_cache.get_calls) == 2


@respx.mock
def test_nfl_client_default_league_does_not_break_teams_cache_key() -> None:
    # Sanity check that caching composes correctly with NFLClient's
    # default_league injection -- two different leagues shouldn't collide.
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = NFLClient(api_key="test-key")

    client.get_teams()
    client.get_teams(league="NCAA")

    assert route.call_count == 2
