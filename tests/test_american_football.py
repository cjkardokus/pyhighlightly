"""Tests for AmericanFootballClient and NFLClient's league-default behavior."""

from __future__ import annotations

from pyhighlightly.american_football import AmericanFootballClient
from pyhighlightly.nfl import NFLClient


def test_nfl_client_default_league_is_nfl() -> None:
    client = NFLClient(api_key="test-key")
    assert client.default_league == "NFL"


def test_nfl_client_injects_default_league() -> None:
    client = NFLClient(api_key="test-key")
    assert client._with_league_default({}) == {"league": "NFL"}


def test_nfl_client_does_not_override_explicit_league() -> None:
    client = NFLClient(api_key="test-key")
    assert client._with_league_default({"league": "NCAA"}) == {"league": "NCAA"}


def test_nfl_client_does_not_override_explicit_league_type() -> None:
    client = NFLClient(api_key="test-key")
    params = {"leagueType": "college"}
    assert client._with_league_default(params) == {"leagueType": "college"}


def test_nfl_client_does_not_override_explicit_league_name() -> None:
    client = NFLClient(api_key="test-key")
    params = {"leagueName": "Big Ten"}
    assert client._with_league_default(params) == {"leagueName": "Big Ten"}


def test_american_football_client_has_no_default_league() -> None:
    client = AmericanFootballClient(api_key="test-key")
    assert client.default_league is None


def test_american_football_client_does_not_inject_league() -> None:
    client = AmericanFootballClient(api_key="test-key")
    assert client._with_league_default({"season": 2024}) == {"season": 2024}
