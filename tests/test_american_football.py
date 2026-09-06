"""Tests for AmericanFootballClient/NFLClient's team and match endpoints."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from pyhighlightly.american_football import AmericanFootballClient
from pyhighlightly.models.american_football import (
    BoxScoreStatistic,
    Match,
    MatchDetail,
    Standings,
    Team,
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


# -- get_team --


@respx.mock
def test_get_team_returns_single_team() -> None:
    respx.get(f"{BASE_URL}/teams/1").mock(return_value=httpx.Response(200, json=[_TEAM]))
    client = AmericanFootballClient(api_key="test-key")

    team = client.get_team(1)

    assert isinstance(team, Team)
    assert team.id == 1


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


def test_get_team_statistics_rejects_malformed_date_string() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="from_date"):
        client.get_team_statistics(1, from_date="03/05/2024")


def test_get_team_statistics_rejects_non_zero_padded_date_string() -> None:
    client = AmericanFootballClient(api_key="test-key")

    with pytest.raises(ValueError, match="from_date"):
        client.get_team_statistics(1, from_date="2024-3-5")


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

    client.get_matches()

    assert "league" not in route.calls.last.request.url.params


@respx.mock
def test_get_matches_does_not_override_explicit_league() -> None:
    route = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=_paginated([_MATCH]))
    )
    client = NFLClient(api_key="test-key")

    client.get_matches(league="NCAA")

    assert route.calls.last.request.url.params["league"] == "NCAA"


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
    assert match.injuries[0].data[0].player.name == "Alvin Kamara"
    assert match.events[0].result == "Punt"
    assert match.predictions is not None
    assert match.predictions.prematch[0].probabilities.away == "69.78%"


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


@pytest.mark.parametrize("value", [7, 10.5, "150", None])
def test_box_score_statistic_value_accepts_loosely_typed_values(
    value: int | float | str | None,
) -> None:
    stat = BoxScoreStatistic(group="Passing", name="Some Stat", value=value)
    assert stat.value == value


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
