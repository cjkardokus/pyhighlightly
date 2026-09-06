"""American Football sport client for Highlightly.

``AmericanFootballClient`` points ``HighlightlyBaseClient`` at Highlightly's
American Football API host and implements the team/match endpoints shared
by every league on that host. League-specific clients (``NFLClient``, and
eventually something like an ``NCAAClient``) subclass it to scope every
request to their own league via ``default_league``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pyhighlightly.client import HighlightlyBaseClient
from pyhighlightly.models.american_football import (
    BoxScoreResult,
    Lineups,
    Match,
    MatchDetail,
    Standings,
    Team,
    TeamBoxScore,
    TeamStatistics,
)
from pyhighlightly.models.common import PaginatedResponse

_DATE_FORMAT = "%Y-%m-%d"
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _format_from_date(from_date: str | date) -> str:
    """Normalize ``from_date`` to the "YYYY-MM-DD" string the API expects.

    Raises ``ValueError`` on a string that isn't already in that exact
    format, rather than silently sending a malformed date to the API.
    """
    if isinstance(from_date, date):
        return from_date.strftime(_DATE_FORMAT)

    if not _DATE_PATTERN.match(from_date):
        raise ValueError(f"from_date must be in 'YYYY-MM-DD' format, got {from_date!r}")
    try:
        datetime.strptime(from_date, _DATE_FORMAT)
    except ValueError as exc:
        raise ValueError(f"from_date must be in 'YYYY-MM-DD' format, got {from_date!r}") from exc
    return from_date


class AmericanFootballClient(HighlightlyBaseClient):
    """Highlightly client for the American Football product surface.

    Subclasses set ``default_league`` to scope every request to a single
    league (see ``NFLClient``); left as ``None`` here since the base
    American Football client isn't tied to any one league.
    """

    base_url: str | None = "https://american-football.highlightly.net"
    default_league: str | None = None

    def get_teams(
        self,
        name: str | None = None,
        display_name: str | None = None,
        abbreviation: str | None = None,
        league: str | None = None,
    ) -> list[Team]:
        """List teams matching the given filters.

        Returns a plain ``list[Team]`` rather than ``PaginatedResponse[Team]``:
        per the API docs, ``/teams`` returns every matching team in a single
        response with no pagination envelope, so wrapping it in one here
        would just be a fiction -- this method's return shape follows what
        the endpoint actually does rather than forcing a shape it doesn't
        have for consistency's sake.
        """
        params: dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if display_name is not None:
            params["displayName"] = display_name
        if abbreviation is not None:
            params["abbreviation"] = abbreviation
        params = self._with_default(params, "league", league or self.default_league)

        response = self._request("GET", "/teams", params=params)
        return [Team.model_validate(item) for item in response.json()]

    def get_team(self, team_id: int) -> Team:
        """Fetch a single team by id."""
        response = self._request("GET", f"/teams/{team_id}")
        return Team.model_validate(response.json()[0])

    def get_team_statistics(
        self,
        team_id: int,
        from_date: str | date,
        timezone: str | None = None,
    ) -> TeamStatistics:
        """Fetch a team's season statistics as of ``from_date``.

        ``from_date`` accepts either a string already in "YYYY-MM-DD"
        format, or a ``datetime.date`` (formatted internally). Both are
        accepted deliberately: an Airflow ``{{ ds }}`` template renders the
        execution date as a string in exactly that format, which is the
        primary expected caller pattern for a scheduled poller, while a
        plain ``date`` object is also accepted for ergonomic direct use. A
        string not already in that format raises ``ValueError`` rather than
        being sent to the API as-is.
        """
        params: dict[str, Any] = {"fromDate": _format_from_date(from_date)}
        params = self._with_default(params, "timezone", timezone)

        response = self._request("GET", f"/teams/statistics/{team_id}", params=params)
        return TeamStatistics.model_validate(response.json()[0])

    def get_matches(
        self,
        date: str | None = None,
        season: int | None = None,
        home_team_id: int | None = None,
        away_team_id: int | None = None,
        home_team_name: str | None = None,
        away_team_name: str | None = None,
        home_team_abbreviation: str | None = None,
        away_team_abbreviation: str | None = None,
        home_team_display_name: str | None = None,
        away_team_display_name: str | None = None,
        league: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> PaginatedResponse[Match]:
        """Fetch one page of matches matching the given filters.

        This is a single request that returns a single page, regardless of
        how many matches match the filters in total -- it never paginates
        on its own. Use ``client.paginate(client.get_matches, ...)``
        explicitly if you want to walk every page of a large result set.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if date is not None:
            params["date"] = date
        if season is not None:
            params["season"] = season
        if home_team_id is not None:
            params["homeTeamId"] = home_team_id
        if away_team_id is not None:
            params["awayTeamId"] = away_team_id
        if home_team_name is not None:
            params["homeTeamName"] = home_team_name
        if away_team_name is not None:
            params["awayTeamName"] = away_team_name
        if home_team_abbreviation is not None:
            params["homeTeamAbbreviation"] = home_team_abbreviation
        if away_team_abbreviation is not None:
            params["awayTeamAbbreviation"] = away_team_abbreviation
        if home_team_display_name is not None:
            params["homeTeamDisplayName"] = home_team_display_name
        if away_team_display_name is not None:
            params["awayTeamDisplayName"] = away_team_display_name
        params = self._with_default(params, "league", league or self.default_league)

        response = self._request("GET", "/matches", params=params)
        return PaginatedResponse[Match].model_validate(response.json())

    def get_match(self, match_id: int) -> MatchDetail:
        """Fetch full detail for a single match, including venue, weather,
        per-team statistics, injuries, play-by-play events, and predictions.
        """
        response = self._request("GET", f"/matches/{match_id}")
        return MatchDetail.model_validate(response.json()[0])

    def get_standings(
        self,
        league_type: str | None = None,
        league_name: str | None = None,
        abbreviation: str | None = None,
        year: int | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> PaginatedResponse[Standings]:
        """Fetch standings groups matching the given filters.

        Only ``leagueType`` gets a ``default_league`` fallback (so
        ``NFLClient`` defaults to ``leagueType="NFL"``); ``league_name`` and
        ``abbreviation`` (conference-level scoping, e.g. "AFC"/"NFC") are
        never auto-injected -- conference filtering is an orthogonal, fully
        manual axis distinct from league-level defaulting, so it's always
        opt-in via these explicit arguments.

        Returns ``PaginatedResponse[Standings]``: confirmed against a live
        response, this endpoint's ``limit``/``offset`` are genuine
        pagination over one ``Standings`` group per (conference, season
        type) combination -- not a bare single object, despite what a
        single-example doc reading might suggest.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if league_name is not None:
            params["leagueName"] = league_name
        if abbreviation is not None:
            params["abbreviation"] = abbreviation
        if year is not None:
            params["year"] = year
        params = self._with_default(params, "leagueType", league_type or self.default_league)

        response = self._request("GET", "/standings", params=params)
        return PaginatedResponse[Standings].model_validate(response.json())

    def get_lineups(self, match_id: int) -> Lineups:
        """Fetch both teams' lineups for a match."""
        response = self._request("GET", f"/lineups/{match_id}")
        return Lineups.model_validate(response.json())

    def get_box_score(self, match_id: int) -> BoxScoreResult:
        """Fetch both teams' box scores for a match.

        The raw API response is an unlabeled ``[homeTeam, awayTeam]`` array
        (each element further wrapped in a ``"team"`` key -- see
        ``BoxScoreResult``'s docstring); this unwraps both into the named
        ``.home``/``.away`` result rather than exposing that raw shape.
        """
        home_raw, away_raw = self._request("GET", f"/box-score/{match_id}").json()
        return BoxScoreResult(
            home=TeamBoxScore.model_validate(home_raw["team"]),
            away=TeamBoxScore.model_validate(away_raw["team"]),
        )

    def get_last_five_games(self, team_id: int) -> list[Match]:
        """Fetch a team's five most recently completed matches."""
        response = self._request("GET", "/last-five-games", params={"teamId": team_id})
        return [Match.model_validate(item) for item in response.json()]

    def get_head_to_head(self, team_id_one: int, team_id_two: int) -> list[Match]:
        """Fetch the match history between two teams."""
        response = self._request(
            "GET",
            "/head-2-head",
            params={"teamIdOne": team_id_one, "teamIdTwo": team_id_two},
        )
        return [Match.model_validate(item) for item in response.json()]
