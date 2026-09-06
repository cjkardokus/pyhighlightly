"""Tests for AmericanFootballClient/NFLClient's team and match endpoints."""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import httpx
import pytest
import respx
from pydantic import ValidationError

from pyhighlightly.american_football import AmericanFootballClient
from pyhighlightly.exceptions import HighlightlyNotFoundError, HighlightlyResponseError
from pyhighlightly.models.american_football import (
    BoxScoreStatistic,
    Highlight,
    HighlightCategory,
    Match,
    MatchDetail,
    MatchStateInfo,
    Player,
    PlayerStatistics,
    PlayerSummary,
    Score,
    Standings,
    Team,
    TeamStatistic,
)
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

_TEAM_NO_LEAGUE = {k: v for k, v in _TEAM.items() if k != "league"}

_STATE = {
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
}

_MATCH = {
    "id": 1,
    "round": "Regular Season - 32",
    "date": "2023-05-20T15:30:00.000Z",
    "league": "NFL",
    "season": 2023,
    "awayTeam": _TEAM_NO_LEAGUE,
    "homeTeam": _TEAM_NO_LEAGUE,
    "state": _STATE,
}

_MATCH_DETAIL = {
    **_MATCH,
    "venue": {"city": "Baltimore", "name": "M&T Bank Stadium", "state": "MD"},
    "forecast": {"status": "cloudy", "temperature": "11.97°C"},
    "matchStatistics": {
        "homeTeam": {"statistics": [{"name": "Rushing Attempts", "value": 34}]},
        "awayTeam": {"statistics": [{"name": "Rushing Attempts", "value": 34}]},
    },
    "injuries": [
        {
            "team": _TEAM,
            "data": [
                {
                    "status": "Questionable",
                    "player": {"name": "Alvin Kamara", "jersey": 41, "position": "Running Back"},
                }
            ],
        }
    ],
    "events": [
        {
            "start": {"clock": "11:43", "period": "1st quarter", "yardLine": 40},
            "end": {"clock": "11:43", "period": "1st quarter", "yardLine": 40},
            "team": _TEAM,
            "plays": ["string"],
            "playDetails": [
                {
                    "start": {
                        "down": 3,
                        "distance": 7,
                        "yardLine": 71,
                        "yardsToEndzone": 29,
                        "possessionText": "DET 29",
                    },
                    "end": {
                        "down": 3,
                        "distance": 7,
                        "yardLine": 71,
                        "yardsToEndzone": 29,
                        "possessionText": "DET 29",
                    },
                    "text": "C.Brown up the middle to CIN 31 for 5 yards (D.White).",
                    "type": "Pass Reception",
                    "period": 1,
                    "clock": "14:53",
                    "isPenalty": False,
                }
            ],
            "result": "Punt",
            "description": "5 plays, 6 yards, 3:17",
            "isScoringPlay": False,
        }
    ],
    "predictions": {
        "prematch": [
            {
                "type": "prematch",
                "modelType": "three-way",
                "generatedAt": "2025-03-12T19:00:20.000Z",
                "description": "Team A is most likely to win...",
                "probabilities": {"home": "30.22%", "draw": "0.00%", "away": "69.78%"},
            }
        ],
        "live": [],
    },
}

_TEAM_STATISTICS = {
    "total": {
        "games": {"played": 67, "wins": 24, "loses": 43},
        "points": {"scored": 1369, "received": 1619},
    },
    "home": {
        "games": {"played": 33, "wins": 13, "loses": 20},
        "points": {"scored": 694, "received": 713},
    },
    "away": {
        "games": {"played": 34, "wins": 11, "loses": 23},
        "points": {"scored": 675, "received": 906},
    },
    "leagueName": "NFL",
    "round": "regular-season",
}


def _paginated(data: list[object]) -> dict[str, object]:
    return {
        "data": data,
        "pagination": {"totalCount": len(data), "offset": 0, "limit": 100},
        "plan": {"tier": "BASIC", "message": "Some results might be hidden with FREE tier"},
    }


# -- generic _with_default (inherited from HighlightlyBaseClient) --


def test_nfl_client_default_league_is_nfl() -> None:
    client = NFLClient(api_key="test-key")
    assert client.default_league == "NFL"


def test_with_default_injects_default_league() -> None:
    client = NFLClient(api_key="test-key")
    assert client._with_default({}, "league", client.default_league) == {"league": "NFL"}


def test_with_default_does_not_override_explicit_value() -> None:
    client = NFLClient(api_key="test-key")
    params = {"league": "NCAA"}
    assert client._with_default(params, "league", client.default_league) == {"league": "NCAA"}


def test_american_football_client_has_no_default_league() -> None:
    client = AmericanFootballClient(api_key="test-key")
    assert client.default_league is None


def test_with_default_skips_none_value() -> None:
    client = AmericanFootballClient(api_key="test-key")
    params = {"season": 2024}
    assert client._with_default(params, "league", client.default_league) == {"season": 2024}


# -- get_teams --


@respx.mock
def test_get_teams_returns_plain_list_not_paginated() -> None:
    respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM, _TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    teams = client.get_teams()

    assert isinstance(teams, list)
    assert len(teams) == 2
    assert all(isinstance(team, Team) for team in teams)
    assert teams[0].displayName == "New Orleans Saints"


@respx.mock
def test_get_teams_applies_default_league_for_nfl_client() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = NFLClient(api_key="test-key")

    client.get_teams()

    assert route.calls.last.request.url.params["league"] == "NFL"


@respx.mock
def test_get_teams_omits_league_for_base_client() -> None:
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    client.get_teams()

    assert "league" not in route.calls.last.request.url.params


@pytest.mark.parametrize(
    ("kwarg", "query_key", "value"),
    [
        ("name", "name", "Saints"),
        ("display_name", "displayName", "New Orleans Saints"),
        ("abbreviation", "abbreviation", "NO"),
    ],
)
@respx.mock
def test_get_teams_sends_each_filter_param_correctly(
    kwarg: str, query_key: str, value: str
) -> None:
    # A typo in any one of these snake_case -> camelCase mappings would be
    # invisible to every other test (which only ever exercise league/season
    # defaults), to mypy, and to ruff -- it would only ever surface as a
    # silently-unfiltered live result.
    route = respx.get(f"{BASE_URL}/teams").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    client.get_teams(**cast("dict[str, Any]", {kwarg: value}))

    assert route.calls.last.request.url.params[query_key] == value


# -- force_refresh is keyword-only on every endpoint method --


def test_force_refresh_cannot_be_passed_positionally_on_a_single_id_method() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(TypeError, match="positional argument"):
        client.get_team(1, True)  # type: ignore[call-arg]


def test_force_refresh_cannot_be_passed_positionally_on_a_two_id_method() -> None:
    # A second representative shape: two required positional args ahead of
    # force_refresh, not just one -- confirms the `*,` separator was placed
    # correctly regardless of how many positional params precede it.
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(TypeError, match="positional argument"):
        client.get_head_to_head(1, 2, True)  # type: ignore[call-arg]


# -- get_team --


@respx.mock
def test_get_team_returns_single_team() -> None:
    respx.get(f"{BASE_URL}/teams/1").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    team = client.get_team(1)

    assert isinstance(team, Team)
    assert team.id == 1


@respx.mock
def test_get_team_raises_not_found_for_empty_array() -> None:
    respx.get(f"{BASE_URL}/teams/999").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_team(999)

    assert exc_info.value.resource_id == 999
    assert exc_info.value.url == f"{BASE_URL}/teams/999"


# -- get_team_statistics --


@respx.mock
def test_get_team_statistics_formats_date_object() -> None:
    route = respx.get(f"{BASE_URL}/teams/statistics/1").mock(
        return_value=httpx.Response(200, json=[_TEAM_STATISTICS])
    )
    client = AmericanFootballClient(api_key="test-key")

    stats = client.get_team_statistics(1, from_date=date(2024, 3, 5))

    assert route.calls.last.request.url.params["fromDate"] == "2024-03-05"
    assert stats.total.games.played == 67
    assert stats.leagueName == "NFL"


@respx.mock
def test_get_team_statistics_accepts_valid_date_string() -> None:
    route = respx.get(f"{BASE_URL}/teams/statistics/1").mock(
        return_value=httpx.Response(200, json=[_TEAM_STATISTICS])
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_team_statistics(1, from_date="2024-03-05")

    assert route.calls.last.request.url.params["fromDate"] == "2024-03-05"


@respx.mock
def test_get_team_statistics_raises_not_found_for_empty_array() -> None:
    respx.get(f"{BASE_URL}/teams/statistics/999").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_team_statistics(999, from_date="2024-03-05")

    assert exc_info.value.resource_id == 999


def test_get_team_statistics_rejects_malformed_date_string() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="from_date"):
        client.get_team_statistics(1, from_date="03/05/2024")


def test_get_team_statistics_rejects_non_zero_padded_date_string() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="from_date"):
        client.get_team_statistics(1, from_date="2024-3-5")


@pytest.mark.parametrize("invalid_date", ["2024-02-31", "2024-13-01"])
def test_get_team_statistics_rejects_well_formed_but_impossible_date(invalid_date: str) -> None:
    # Distinct from the two tests above: these two strings pass the
    # YYYY-MM-DD regex check (_DATE_PATTERN) but describe a date that
    # doesn't exist -- Feb 31st, and a 13th month. Only strptime itself
    # catches this, in _format_from_date's second guard. Untested before
    # this, a refactor that dropped the strptime call would have kept
    # every other test green while silently sending an impossible date to
    # the API.
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="from_date") as exc_info:
        client.get_team_statistics(1, from_date=invalid_date)

    assert invalid_date in str(exc_info.value)


# -- get_matches --


@respx.mock
def test_get_matches_applies_default_league_for_nfl_client() -> None:
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = NFLClient(api_key="test-key")

    result = client.get_matches()

    assert route.calls.last.request.url.params["league"] == "NFL"
    assert result.data[0].id == 1
    assert result.pagination.totalCount == 1


@respx.mock
def test_get_matches_omits_league_for_base_client() -> None:
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = AmericanFootballClient(api_key="test-key")

    # season=2024 satisfies the "at least one primary filter" requirement;
    # this test is only checking that "league" itself isn't auto-injected.
    client.get_matches(season=2024)

    assert "league" not in route.calls.last.request.url.params


@respx.mock
def test_get_matches_does_not_override_explicit_league() -> None:
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = NFLClient(api_key="test-key")

    client.get_matches(league="NCAA")

    assert route.calls.last.request.url.params["league"] == "NCAA"


@pytest.mark.parametrize(
    ("kwarg", "query_key", "value"),
    [
        ("date", "date", "2024-01-01"),
        ("home_team_id", "homeTeamId", 5),
        ("away_team_id", "awayTeamId", 7),
        ("home_team_name", "homeTeamName", "Saints"),
        ("away_team_name", "awayTeamName", "Falcons"),
        ("home_team_abbreviation", "homeTeamAbbreviation", "NO"),
        ("away_team_abbreviation", "awayTeamAbbreviation", "ATL"),
        ("home_team_display_name", "homeTeamDisplayName", "New Orleans Saints"),
        ("away_team_display_name", "awayTeamDisplayName", "Atlanta Falcons"),
    ],
)
@respx.mock
def test_get_matches_sends_each_filter_param_correctly(
    kwarg: str, query_key: str, value: int | str
) -> None:
    # Each of these is also itself a valid "primary filter" on its own, so
    # no other kwarg is needed to satisfy _require_at_least_one. A typo in
    # any one of these snake_case -> camelCase mappings would be invisible
    # to every other test, mypy, and ruff -- it would only ever surface as
    # a silently-unfiltered live result.
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_matches(**cast("dict[str, Any]", {kwarg: value}))

    assert route.calls.last.request.url.params[query_key] == str(value)


def test_get_matches_rejects_malformed_date_string() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="date"):
        client.get_matches(date="01/05/2024")


@respx.mock
def test_get_matches_accepts_date_object() -> None:
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_matches(date=date(2024, 3, 5))

    assert route.calls.last.request.url.params["date"] == "2024-03-05"


# -- get_match --


@respx.mock
def test_get_match_returns_match_detail_with_nested_fields() -> None:
    respx.get(f"{BASE_URL}/matches/1").mock(return_value=httpx.Response(200, json=[_MATCH_DETAIL]))
    client = AmericanFootballClient(api_key="test-key")

    match = client.get_match(1)

    assert isinstance(match, MatchDetail)
    assert match.id == 1
    assert match.venue is not None
    assert match.venue.city == "Baltimore"
    assert match.forecast is not None
    assert match.forecast.temperature == "11.97°C"
    assert match.matchStatistics is not None
    assert match.matchStatistics.homeTeam.statistics[0].name == "Rushing Attempts"
    assert match.injuries is not None
    assert match.injuries[0].data[0].player.name == "Alvin Kamara"
    assert match.events is not None
    assert match.events[0].result == "Punt"
    assert match.predictions is not None
    assert match.predictions.prematch[0].probabilities.away == "69.78%"


@respx.mock
def test_get_match_parses_explicit_null_injuries_and_events() -> None:
    # Regression test: Highlightly sends "injuries": null / "events": null
    # explicitly (not merely omitting the keys) for real finished matches
    # -- confirmed live, 3/3, on 2026-09-06. A bare
    # `list[...] = Field(default_factory=list)` only supplies its default
    # for an *absent* key; it does nothing for a key present with an
    # explicit JSON null, so this exact shape used to raise a
    # ValidationError (wrapped as HighlightlyResponseError) instead of
    # parsing -- get_match() was broken for real finished games. Setting
    # the keys to None explicitly here, not omitting them, is the point:
    # an absent-key fixture would not have caught this.
    match_detail_with_explicit_nulls = {**_MATCH_DETAIL, "injuries": None, "events": None}
    respx.get(f"{BASE_URL}/matches/1").mock(
        return_value=httpx.Response(200, json=[match_detail_with_explicit_nulls])
    )
    client = AmericanFootballClient(api_key="test-key")

    match = client.get_match(1)

    assert isinstance(match, MatchDetail)
    assert match.injuries is None
    assert match.events is None


@respx.mock
def test_get_match_raises_not_found_for_empty_array() -> None:
    respx.get(f"{BASE_URL}/matches/999").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_match(999)

    assert exc_info.value.resource_id == 999
    assert exc_info.value.url == f"{BASE_URL}/matches/999"


_STANDINGS_GROUP = {
    "leagueName": "American Football Conference",
    "abbreviation": "AFC",
    "year": 2024,
    "leagueType": "NFL",
    "seasonType": "Preseason",
    "startDate": "2024-08-01T07:00:00.000Z",
    "endDate": "2024-09-05T06:59:00.000Z",
    "data": [
        {
            "team": _TEAM_NO_LEAGUE,
            "statistics": [{"value": "+4", "displayName": "Differential"}],
        }
    ],
}


def _standings_envelope(groups: list[object]) -> dict[str, object]:
    return {
        "data": groups,
        "pagination": {"totalCount": len(groups), "offset": 0, "limit": 10},
        "plan": {"tier": "BASIC", "message": "Some results might be hidden with FREE tier"},
    }


_LINEUP_PLAYER = {
    "id": 45642302,
    "jersey": 11,
    "player": "Logan Woodside",
    "position": "Quarterback",
    "positionAbbreviation": "QB",
    "isStarter": True,
}

_LINEUPS = {
    "home": {"team": _TEAM_NO_LEAGUE, "lineup": [_LINEUP_PLAYER]},
    "away": {"team": _TEAM_NO_LEAGUE, "lineup": [_LINEUP_PLAYER]},
}

_BOX_SCORE_RAW = [
    {
        "team": {
            "id": 92750,
            "logo": "https://example.com/logos/team/92750.png",
            "name": "Eagles",
            "boxScores": [
                {
                    "player": {"id": 60611792, "name": "Jalen Hurts", "jersey": 1},
                    "statistics": [
                        {"group": "Passing", "name": "Total Passing Yards", "value": 221}
                    ],
                }
            ],
        }
    },
    {
        "team": {
            "id": 92764,
            "logo": "https://example.com/logos/team/92764.png",
            "name": "Broncos",
            "boxScores": [
                {
                    "player": {"id": 12345, "name": "Bo Nix", "jersey": None},
                    "statistics": [
                        {"group": "Passing", "name": "Total Passing Yards", "value": "150"}
                    ],
                }
            ],
        }
    },
]


# -- get_standings --


def test_standings_model_parses_a_single_group_without_an_envelope() -> None:
    # Standings itself carries no pagination/plan fields -- those live one
    # level up, on the PaginatedResponse[Standings] that wraps it (see
    # get_standings and Standings' docstring: a live response confirmed the
    # envelope IS present at that outer level, contrary to a first read of
    # the written docs' single-group example).
    standings = Standings.model_validate(_STANDINGS_GROUP)

    assert standings.leagueName == "American Football Conference"
    assert standings.abbreviation == "AFC"
    assert standings.seasonType == "Preseason"
    assert standings.data[0].statistics[0].displayName == "Differential"


@respx.mock
def test_get_standings_returns_paginated_response_of_groups() -> None:
    respx.get(f"{BASE_URL}/standings").mock(
        return_value=httpx.Response(200, json=_standings_envelope([_STANDINGS_GROUP]))
    )
    client = AmericanFootballClient(api_key="test-key")

    result = client.get_standings(year=2024)

    assert result.pagination.totalCount == 1
    assert result.data[0].abbreviation == "AFC"


@respx.mock
def test_get_standings_applies_default_league_type_for_nfl_client() -> None:
    route = respx.get(f"{BASE_URL}/standings").mock(
        return_value=httpx.Response(200, json=_standings_envelope([_STANDINGS_GROUP]))
    )
    client = NFLClient(api_key="test-key")

    client.get_standings()

    assert route.calls.last.request.url.params["leagueType"] == "NFL"


@respx.mock
def test_get_standings_passes_through_explicit_conference_filters() -> None:
    route = respx.get(f"{BASE_URL}/standings").mock(
        return_value=httpx.Response(200, json=_standings_envelope([_STANDINGS_GROUP]))
    )
    client = NFLClient(api_key="test-key")

    client.get_standings(league_name="American Football Conference", abbreviation="AFC")

    params = route.calls.last.request.url.params
    assert params["leagueType"] == "NFL"
    assert params["leagueName"] == "American Football Conference"
    assert params["abbreviation"] == "AFC"


@respx.mock
def test_get_standings_omits_league_type_for_base_client() -> None:
    route = respx.get(f"{BASE_URL}/standings").mock(
        return_value=httpx.Response(200, json=_standings_envelope([_STANDINGS_GROUP]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_standings()

    assert "leagueType" not in route.calls.last.request.url.params


# -- get_lineups --


@respx.mock
def test_get_lineups_parses_home_and_away() -> None:
    respx.get(f"{BASE_URL}/lineups/1").mock(return_value=httpx.Response(200, json=_LINEUPS))
    client = AmericanFootballClient(api_key="test-key")

    lineups = client.get_lineups(1)

    assert lineups.home.team.displayName == "New Orleans Saints"
    assert lineups.home.lineup[0].player == "Logan Woodside"
    assert lineups.away.lineup[0].positionAbbreviation == "QB"


# -- get_box_score --


@respx.mock
def test_get_box_score_maps_raw_array_to_home_and_away_in_order() -> None:
    respx.get(f"{BASE_URL}/box-score/1").mock(return_value=httpx.Response(200, json=_BOX_SCORE_RAW))
    client = AmericanFootballClient(api_key="test-key")

    result = client.get_box_score(1)

    # Order matters: index 0 of the raw array is home, index 1 is away.
    assert result.home.name == "Eagles"
    assert result.home.boxScores[0].player.name == "Jalen Hurts"
    assert result.away.name == "Broncos"
    assert result.away.boxScores[0].player.jersey is None


@respx.mock
def test_get_box_score_raises_not_found_for_empty_array() -> None:
    # Not "one team's box score is missing" (that's the 1-element case
    # below) -- an empty array means nothing has been published at all.
    respx.get(f"{BASE_URL}/box-score/999").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_box_score(999)

    assert exc_info.value.resource_id == 999
    assert exc_info.value.url == f"{BASE_URL}/box-score/999"


@respx.mock
def test_get_box_score_raises_response_error_for_one_element() -> None:
    # A realistic partial-data case: one team's box score is available,
    # the other isn't yet. Distinct from "not found" (see the empty-array
    # test above) -- something exists, just not the complete pair this
    # method promises -- so this is HighlightlyResponseError, not
    # HighlightlyNotFoundError.
    respx.get(f"{BASE_URL}/box-score/1").mock(
        return_value=httpx.Response(200, json=[_BOX_SCORE_RAW[0]])
    )
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyResponseError, match="got 1"):
        client.get_box_score(1)


@pytest.mark.parametrize("value", [7, 10.5, "150", None])
def test_box_score_statistic_value_accepts_loosely_typed_values(
    value: int | float | str | None,
) -> None:
    stat = BoxScoreStatistic(group="Passing", name="Some Stat", value=value)
    assert stat.value == value


@pytest.mark.parametrize("value", [7, 10.5, "150"])
def test_team_statistic_value_accepts_loosely_typed_non_null_values(
    value: int | float | str,
) -> None:
    stat = TeamStatistic(name="Rushing Attempts", value=value)
    assert stat.value == value


def test_team_statistic_value_currently_rejects_none() -> None:
    # Locks in the current non-nullable assumption on TeamStatistic.value
    # (see its docstring): last checked live against get_match() on
    # 2026-09-06 across 3 completed matches (204 individual statistics),
    # no null was observed. If Highlightly is ever seen sending a null
    # here, this test should be updated to expect acceptance (and the
    # model's `| None` added) rather than just deleted.
    with pytest.raises(ValidationError):
        TeamStatistic(name="Rushing Attempts", value=None)  # type: ignore[arg-type]


def test_match_state_info_clock_accepts_int() -> None:
    state = MatchStateInfo(period=3, clock=31, description="In progress", score=Score())
    assert state.clock == 31


def test_match_state_info_clock_currently_rejects_mm_ss_string() -> None:
    # Locks in the narrowed type (see the docstring comment on `clock`):
    # 3 separate in-progress games checked live on 2026-09-06 all reported
    # clock as a plain int, not a "MM:SS" string like MatchEventMarker's
    # own (differently-named) clock field uses. Deliberately not a numeric
    # string like "31" here -- pydantic coerces those to int regardless of
    # this field's declared type, so that wouldn't test the distinction
    # that actually matters. If Highlightly is ever seen sending a
    # "MM:SS"-shaped string on this field, this test should be updated to
    # expect acceptance (and the model re-widened to int | str) rather
    # than just deleted.
    with pytest.raises(ValidationError):
        MatchStateInfo(period=3, clock="11:43", description="In progress", score=Score())  # type: ignore[arg-type]


# -- get_last_five_games / get_head_to_head --


@respx.mock
def test_get_last_five_games_returns_list_of_matches() -> None:
    respx.get(f"{BASE_URL}/last-five-games").mock(return_value=httpx.Response(200, json=[_MATCH]))
    client = AmericanFootballClient(api_key="test-key")

    matches = client.get_last_five_games(1)

    assert matches == [Match.model_validate(_MATCH)]


@respx.mock
def test_get_last_five_games_sends_team_id_param() -> None:
    route = respx.get(f"{BASE_URL}/last-five-games").mock(
        return_value=httpx.Response(200, json=[_MATCH])
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_last_five_games(42)

    assert route.calls.last.request.url.params["teamId"] == "42"


@respx.mock
def test_get_head_to_head_returns_list_of_matches() -> None:
    respx.get(f"{BASE_URL}/head-2-head").mock(return_value=httpx.Response(200, json=[_MATCH]))
    client = AmericanFootballClient(api_key="test-key")

    matches = client.get_head_to_head(1, 2)

    assert matches == [Match.model_validate(_MATCH)]


@respx.mock
def test_get_head_to_head_sends_both_team_id_params() -> None:
    route = respx.get(f"{BASE_URL}/head-2-head").mock(
        return_value=httpx.Response(200, json=[_MATCH])
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_head_to_head(1, 2)

    params = route.calls.last.request.url.params
    assert params["teamIdOne"] == "1"
    assert params["teamIdTwo"] == "2"


# -- "at least one primary filter" validation --


def test_get_matches_rejects_only_secondary_params() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="get_matches") as exc_info:
        client.get_matches(limit=10, offset=0)

    # The actual params passed are in the message too, so a caller several
    # stack frames away from this call doesn't have to reproduce it to see
    # what was (and wasn't) provided.
    assert "'limit': 10" in str(exc_info.value)
    assert "'offset': 0" in str(exc_info.value)


@respx.mock
def test_get_matches_succeeds_with_a_primary_filter() -> None:
    respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = AmericanFootballClient(api_key="test-key")

    result = client.get_matches(season=2024)

    assert result.data[0].id == 1


def test_get_highlights_rejects_only_secondary_params() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="get_highlights") as exc_info:
        client.get_highlights(limit=10, offset=0)

    assert "'limit': 10" in str(exc_info.value)
    assert "'offset': 0" in str(exc_info.value)


def test_get_highlights_default_league_counts_as_a_primary_filter() -> None:
    # NFLClient's default_league="NFL" gets injected under "leagueName" before
    # the primary-filter check runs, so a zero-explicit-filter call from
    # NFLClient is *not* rejected the way it would be from the base client.
    client = NFLClient(api_key="test-key")

    with respx.mock:
        respx.get(f"{BASE_URL}/highlights").mock(
            return_value=httpx.Response(200, json=_paginated([_HIGHLIGHT]))
        )
        client.get_highlights()  # should not raise


# -- get_highlights / get_highlight --

_HIGHLIGHT_MATCH = {
    "id": 569261,
    "round": "regular-season",
    "date": "2026-09-03T23:00:00.000Z",
    "league": "NCAA",
    "season": 2026,
    "homeTeam": _TEAM_NO_LEAGUE,
    "awayTeam": _TEAM_NO_LEAGUE,
}

_HIGHLIGHT = {
    "id": 105289,
    "type": "VERIFIED",
    "imgUrl": "https://i.ytimg.com/vi/tKnSG1ZW5W8/hqdefault.jpg",
    "title": "Game Preview",
    "description": None,
    "url": "https://www.youtube.com/watch?v=tKnSG1ZW5W8",
    "embedUrl": "https://www.youtube.com/embed/tKnSG1ZW5W8",
    "match": _HIGHLIGHT_MATCH,
    "channel": "NFL",
    "source": "youtube",
    "category": "pre-match-content",
}


@respx.mock
def test_get_highlights_applies_default_league_for_nfl_client() -> None:
    route = respx.get(f"{BASE_URL}/highlights").mock(
        return_value=httpx.Response(200, json=_paginated([_HIGHLIGHT]))
    )
    client = NFLClient(api_key="test-key")

    client.get_highlights(season=2024)

    assert route.calls.last.request.url.params["leagueName"] == "NFL"


@respx.mock
def test_get_highlights_omits_league_name_for_base_client() -> None:
    route = respx.get(f"{BASE_URL}/highlights").mock(
        return_value=httpx.Response(200, json=_paginated([_HIGHLIGHT]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_highlights(season=2024)

    assert "leagueName" not in route.calls.last.request.url.params


@pytest.mark.parametrize(
    ("kwarg", "query_key", "value"),
    [
        ("date", "date", "2024-01-01"),
        ("match_id", "matchId", 42),
        ("home_team_id", "homeTeamId", 5),
        ("away_team_id", "awayTeamId", 7),
        ("home_team_name", "homeTeamName", "Saints"),
        ("away_team_name", "awayTeamName", "Falcons"),
        ("home_team_abbreviation", "homeTeamAbbreviation", "NO"),
        ("away_team_abbreviation", "awayTeamAbbreviation", "ATL"),
        ("home_team_display_name", "homeTeamDisplayName", "New Orleans Saints"),
        ("away_team_display_name", "awayTeamDisplayName", "Atlanta Falcons"),
    ],
)
@respx.mock
def test_get_highlights_sends_each_filter_param_correctly(
    kwarg: str, query_key: str, value: int | str
) -> None:
    # Same nine params as get_matches, plus matchId -- see that test's
    # comment for why each of these is checked individually.
    route = respx.get(f"{BASE_URL}/highlights").mock(
        return_value=httpx.Response(200, json=_paginated([_HIGHLIGHT]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_highlights(**cast("dict[str, Any]", {kwarg: value}))

    assert route.calls.last.request.url.params[query_key] == str(value)


def test_get_highlights_rejects_malformed_date_string() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="date"):
        client.get_highlights(date="01/05/2024")


@respx.mock
def test_get_highlights_accepts_date_object() -> None:
    route = respx.get(f"{BASE_URL}/highlights").mock(
        return_value=httpx.Response(200, json=_paginated([_HIGHLIGHT]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_highlights(date=date(2024, 3, 5))

    assert route.calls.last.request.url.params["date"] == "2024-03-05"


@respx.mock
def test_get_highlight_returns_single_highlight_instance() -> None:
    respx.get(f"{BASE_URL}/highlights/105289").mock(
        return_value=httpx.Response(200, json=[_HIGHLIGHT])
    )
    client = AmericanFootballClient(api_key="test-key")

    highlight = client.get_highlight(105289)

    assert isinstance(highlight, Highlight)
    assert highlight.category == HighlightCategory.PRE_MATCH_CONTENT
    assert highlight.match.id == 569261


@respx.mock
def test_get_highlight_raises_not_found_for_empty_array() -> None:
    respx.get(f"{BASE_URL}/highlights/999").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_highlight(999)

    assert exc_info.value.resource_id == 999
    assert exc_info.value.url == f"{BASE_URL}/highlights/999"


def test_highlight_category_parses_known_value() -> None:
    highlight = Highlight.model_validate(_HIGHLIGHT)
    assert highlight.category is HighlightCategory.PRE_MATCH_CONTENT


def test_highlight_category_coerces_unrecognized_value_to_other() -> None:
    highlight = Highlight.model_validate({**_HIGHLIGHT, "category": "some-brand-new-category"})
    assert highlight.category is HighlightCategory.OTHER


# -- get_players --

_PLAYER = {"id": 36017, "fullName": "Tom Brady", "logo": None}


@respx.mock
def test_get_players_returns_paginated_response_of_players() -> None:
    respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = AmericanFootballClient(api_key="test-key")

    result = client.get_players()

    assert isinstance(result.data[0], Player)
    assert result.data[0].fullName == "Tom Brady"
    assert result.pagination.totalCount == 1


@respx.mock
def test_get_players_sends_name_filter() -> None:
    route = respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_players(name="Brady")

    assert route.calls.last.request.url.params["name"] == "Brady"


@respx.mock
def test_get_players_omits_name_filter_when_not_given() -> None:
    route = respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_players()

    assert "name" not in route.calls.last.request.url.params


@respx.mock
def test_get_players_never_sends_a_league_param_even_via_nfl_client() -> None:
    # Deliberate, not a gap -- see get_players' docstring. /players has no
    # league-scoping parameter at all; confirmed live, a league=NFL query
    # is rejected outright with HTTP 400 ("property league should not
    # exist"), not silently ignored. This pins that NFLClient's
    # default_league is correctly never applied here, so a future change
    # that reflexively adds _with_default(..., "league", ...) -- matching
    # every other list endpoint -- doesn't silently reintroduce a call the
    # live API is confirmed to reject.
    route = respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = NFLClient(api_key="test-key")

    client.get_players()

    assert "league" not in route.calls.last.request.url.params


@respx.mock
def test_get_players_default_limit_is_1000() -> None:
    # Distinct from get_matches' limit=100 and get_highlights' limit=40
    # defaults -- confirm this endpoint's own default specifically, not
    # just that some limit is sent.
    route = respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_players()

    assert route.calls.last.request.url.params["limit"] == "1000"


@respx.mock
def test_get_players_explicit_limit_overrides_default() -> None:
    route = respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = AmericanFootballClient(api_key="test-key")

    client.get_players(limit=25)

    assert route.calls.last.request.url.params["limit"] == "25"


@respx.mock
def test_get_players_accepts_zero_filter_call() -> None:
    # Unlike get_matches/get_highlights, get_players has no primary-filter
    # requirement -- a call with no arguments at all should succeed.
    respx.get(f"{BASE_URL}/players").mock(
        return_value=httpx.Response(200, json=_paginated([_PLAYER]))
    )
    client = AmericanFootballClient(api_key="test-key")

    result = client.get_players()

    assert result.data[0].id == 36017


# -- get_player / get_player_statistics --

_PLAYER_PROFILE = {
    "id": 36017,
    "logo": None,
    "fullName": "Tom Brady",
    "profile": {
        "fullName": "Tom Brady",
        "birthPlace": "San Mateo, CA, USA",
        "birthDate": "Aug 3, 1977",
        "height": "6' 4\"",
        "jersey": "12",
        "weight": "225 lbs",
        "isActive": False,
        "position": {"main": "Quarterback", "abbreviation": "QB"},
        "draft": {"round": 6, "year": 2000, "pick": 199},
        "team": _TEAM_NO_LEAGUE,
    },
}

_PLAYER_STATISTICS = {
    "id": 36017,
    "logo": None,
    "fullName": "Tom Brady",
    "perSeason": [
        {
            "stats": [
                {"name": "Total Games Played", "value": 17, "category": "General"},
                {"name": "Win Percentage", "value": "0.647", "category": "General"},
                {"name": "Some Unreported Stat", "value": None, "category": "General"},
            ],
            "teams": [_TEAM_NO_LEAGUE],
            "league": "NFL",
            "season": 2021,
            "seasonBreakdown": "Entire",
        }
    ],
}


@respx.mock
def test_get_player_returns_player_summary_with_profile() -> None:
    respx.get(f"{BASE_URL}/players/36017").mock(
        return_value=httpx.Response(200, json=[_PLAYER_PROFILE])
    )
    client = AmericanFootballClient(api_key="test-key")

    player = client.get_player(36017)

    assert isinstance(player, PlayerSummary)
    assert player.fullName == "Tom Brady"
    assert player.profile.jersey == "12"
    assert player.profile.position.abbreviation == "QB"
    assert player.profile.draft is not None
    assert player.profile.draft.year == 2000


@respx.mock
def test_get_player_raises_not_found_for_empty_array() -> None:
    respx.get(f"{BASE_URL}/players/999").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_player(999)

    assert exc_info.value.resource_id == 999
    assert exc_info.value.url == f"{BASE_URL}/players/999"


@respx.mock
def test_get_player_statistics_returns_per_season_stats() -> None:
    respx.get(f"{BASE_URL}/players/36017/statistics").mock(
        return_value=httpx.Response(200, json=[_PLAYER_STATISTICS])
    )
    client = AmericanFootballClient(api_key="test-key")

    stats = client.get_player_statistics(36017)

    assert isinstance(stats, PlayerStatistics)
    season = stats.perSeason[0]
    assert season.league == "NFL"
    assert season.seasonBreakdown == "Entire"
    values_by_name = {s.name: s.value for s in season.stats}
    assert values_by_name["Total Games Played"] == 17
    assert values_by_name["Win Percentage"] == "0.647"
    assert values_by_name["Some Unreported Stat"] is None


@respx.mock
def test_get_player_statistics_raises_not_found_for_empty_array() -> None:
    respx.get(f"{BASE_URL}/players/999/statistics").mock(return_value=httpx.Response(200, json=[]))
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(HighlightlyNotFoundError) as exc_info:
        client.get_player_statistics(999)

    assert exc_info.value.resource_id == 999
    assert exc_info.value.url == f"{BASE_URL}/players/999/statistics"
