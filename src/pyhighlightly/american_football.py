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
from typing import Any, ClassVar

import httpx

from pyhighlightly.client import HighlightlyBaseClient
from pyhighlightly.exceptions import HighlightlyNotFoundError, HighlightlyResponseError
from pyhighlightly.models.american_football import (
    BoxScoreResult,
    Highlight,
    Lineups,
    Match,
    MatchDetail,
    Player,
    PlayerStatistics,
    PlayerSummary,
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


def _first_or_not_found(response: httpx.Response, *, resource: str, resource_id: int) -> Any:
    """Return the first element of a single-resource array response.

    Several endpoints (``/teams/{id}``, ``/matches/{id}``, ``/players/{id}``,
    ...) wrap a single resource in a one-element array; an empty array is
    the API's way of saying that id doesn't exist -- confirmed against a
    live response, not documented behavior, but consistent across every
    one of these endpoints. Raises ``HighlightlyNotFoundError`` rather than
    letting an empty array reach a bare ``[0]`` index (which would raise a
    generic ``IndexError`` instead).

    ``resource`` is a short human-readable name (e.g. ``"team"``) used only
    in the error message; ``resource_id`` becomes the exception's
    ``resource_id`` attribute.
    """
    items = response.json()
    if not items:
        raise HighlightlyNotFoundError(
            f"No {resource} found with id={resource_id}",
            url=str(response.request.url),
            response_body=response.text,
            resource_id=resource_id,
        )
    return items[0]


class AmericanFootballClient(HighlightlyBaseClient):
    """Highlightly client for the American Football product surface.

    Subclasses set ``default_league`` to scope every request to a single
    league (see ``NFLClient``); left as ``None`` here since the base
    American Football client isn't tied to any one league.
    """

    base_url: str | None = "https://american-football.highlightly.net"
    default_league: str | None = None

    #: Per-endpoint default cache TTLs, in seconds. Reasoning per bucket,
    #: citing Highlightly's documented data-refresh cadence where one
    #: exists (see the "Caching" note on ``HighlightlyBaseClient`` for how
    #: these merge with a constructor-supplied ``cache_ttls`` override):
    #:
    #: - **Never cached (0):** ``get_matches``, ``get_match``,
    #:   ``get_box_score``, ``get_highlights`` -- docs say matches/live
    #:   scores and box scores both refresh "once a minute" and highlights
    #:   "once a minute" too; any TTL bucket coarser than that would risk
    #:   serving visibly stale live data. ``get_lineups`` is also never
    #:   cached: docs say lineups "should be queried up to a few hours
    #:   before the game starts," implying they're still being finalized
    #:   during exactly the window callers query them in.
    #: - **6 hours (21600s):** ``get_teams``, ``get_team`` -- no documented
    #:   refresh interval; team metadata (name/logo/abbreviation) changes on
    #:   the order of months, not minutes. ``get_players``, ``get_player`` --
    #:   docs say the players list refreshes as often as "15 minutes," but
    #:   roster membership and player bios change infrequently enough in
    #:   practice that a much longer TTL is used to conserve quota; call
    #:   with ``force_refresh=True`` if you need to catch a roster change
    #:   sooner. ``get_player_statistics`` -- docs say "once a day"; caching
    #:   for 6 hours stays well inside that cadence while still cutting
    #:   several redundant calls out of a busy polling day.
    #: - **30 minutes (1800s):** ``get_standings`` -- docs say standings
    #:   update "up to an hour after a match ... is finished"; half that
    #:   window is a safety margin against serving data stale past the
    #:   documented worst case. ``get_team_statistics`` -- docs say
    #:   "immediately once a match is finished," but between matches this
    #:   data is static, so 30 minutes trades a little staleness right after
    #:   a game ends for meaningfully fewer requests the rest of the time.
    #: - **15 minutes (900s):** ``get_last_five_games``, ``get_head_to_head``
    #:   -- docs say last-five-games updates "immediately once a game is
    #:   considered finished" (head-to-head has no documented interval, but
    #:   is the same kind of "recent game history" query); 15 minutes is a
    #:   middle ground between that and quota economy.
    DEFAULT_CACHE_TTLS: ClassVar[dict[str, int]] = {
        "get_teams": 21600,
        "get_team": 21600,
        "get_players": 21600,
        "get_player": 21600,
        "get_player_statistics": 21600,
        "get_standings": 1800,
        "get_team_statistics": 1800,
        "get_last_five_games": 900,
        "get_head_to_head": 900,
        "get_matches": 0,
        "get_match": 0,
        "get_box_score": 0,
        "get_lineups": 0,
        "get_highlights": 0,
    }

    def get_teams(
        self,
        name: str | None = None,
        display_name: str | None = None,
        abbreviation: str | None = None,
        league: str | None = None,
        *,
        force_refresh: bool = False,
    ) -> list[Team]:
        """List teams matching the given filters.

        Returns a plain ``list[Team]`` rather than ``PaginatedResponse[Team]``:
        per the API docs, ``/teams`` returns every matching team in a single
        response with no pagination envelope, so wrapping it in one here
        would just be a fiction -- this method's return shape follows what
        the endpoint actually does rather than forcing a shape it doesn't
        have for consistency's sake.

        Cached for 6 hours by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        params: dict[str, Any] = {}
        if name is not None:
            params["name"] = name
        if display_name is not None:
            params["displayName"] = display_name
        if abbreviation is not None:
            params["abbreviation"] = abbreviation
        params = self._with_default(params, "league", league or self.default_league)

        return self._cached_request(
            "get_teams",
            "GET",
            "/teams",
            params,
            lambda response: [Team.model_validate(item) for item in response.json()],
            force_refresh=force_refresh,
        )

    def get_team(self, team_id: int, *, force_refresh: bool = False) -> Team:
        """Fetch a single team by id.

        Raises ``HighlightlyNotFoundError`` if ``team_id`` doesn't exist.

        Cached for 6 hours by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        return self._cached_request(
            "get_team",
            "GET",
            f"/teams/{team_id}",
            {},
            lambda response: Team.model_validate(
                _first_or_not_found(response, resource="team", resource_id=team_id)
            ),
            force_refresh=force_refresh,
        )

    def get_team_statistics(
        self,
        team_id: int,
        from_date: str | date,
        timezone: str | None = None,
        *,
        force_refresh: bool = False,
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

        Raises ``HighlightlyNotFoundError`` if ``team_id`` doesn't exist.

        Cached for 30 minutes by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        params: dict[str, Any] = {"fromDate": _format_from_date(from_date)}
        params = self._with_default(params, "timezone", timezone)

        return self._cached_request(
            "get_team_statistics",
            "GET",
            f"/teams/statistics/{team_id}",
            params,
            lambda response: TeamStatistics.model_validate(
                _first_or_not_found(response, resource="team", resource_id=team_id)
            ),
            force_refresh=force_refresh,
        )

    def get_matches(
        self,
        date: str | date | None = None,
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
        *,
        force_refresh: bool = False,
    ) -> PaginatedResponse[Match]:
        """Fetch one page of matches matching the given filters.

        This is a single request that returns a single page, regardless of
        how many matches match the filters in total -- it never paginates
        on its own. Use ``client.paginate(client.get_matches, ...)``
        explicitly if you want to walk every page of a large result set.

        ``date`` accepts either a string already in "YYYY-MM-DD" format or
        a ``datetime.date`` (formatted internally) -- the same dual-type
        acceptance as ``get_team_statistics``' ``from_date``, for the same
        reason: an Airflow ``{{ ds }}`` template renders as a string in
        that exact format, while a plain ``date`` object is also accepted
        for direct use. A string not already in that format raises
        ``ValueError`` rather than being sent to the API as-is -- a
        malformed date was previously sent through unvalidated, spending a
        real request on a call guaranteed to fail.

        Highlightly's docs state: "At least one primary query parameter
        needs to be specified before you can retrieve the data" for this
        endpoint (``timezone``/``limit``/``offset`` don't count). That's
        checked client-side before the network call, so a call missing
        every primary filter fails fast with ``ValueError`` instead of
        spending a request on a call the API is documented to reject.

        Never cached (see ``DEFAULT_CACHE_TTLS``): match/live-score data
        refreshes "once a minute" per the docs, so ``force_refresh`` has no
        effect here beyond what already happens on every call.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if date is not None:
            params["date"] = _format_from_date(date)
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
        self._require_at_least_one(params, {"timezone", "limit", "offset"}, "get_matches")

        return self._cached_request(
            "get_matches",
            "GET",
            "/matches",
            params,
            lambda response: PaginatedResponse[Match].model_validate(response.json()),
            force_refresh=force_refresh,
        )

    def get_match(self, match_id: int, *, force_refresh: bool = False) -> MatchDetail:
        """Fetch full detail for a single match, including venue, weather,
        per-team statistics, injuries, play-by-play events, and predictions.

        Raises ``HighlightlyNotFoundError`` if ``match_id`` doesn't exist.

        Never cached (see ``DEFAULT_CACHE_TTLS``): a match in progress
        changes at least as fast as the matches list itself.
        """
        return self._cached_request(
            "get_match",
            "GET",
            f"/matches/{match_id}",
            {},
            lambda response: MatchDetail.model_validate(
                _first_or_not_found(response, resource="match", resource_id=match_id)
            ),
            force_refresh=force_refresh,
        )

    def get_standings(
        self,
        league_type: str | None = None,
        league_name: str | None = None,
        abbreviation: str | None = None,
        year: int | None = None,
        limit: int = 10,
        offset: int = 0,
        *,
        force_refresh: bool = False,
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

        Cached for 30 minutes by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if league_name is not None:
            params["leagueName"] = league_name
        if abbreviation is not None:
            params["abbreviation"] = abbreviation
        if year is not None:
            params["year"] = year
        params = self._with_default(params, "leagueType", league_type or self.default_league)

        return self._cached_request(
            "get_standings",
            "GET",
            "/standings",
            params,
            lambda response: PaginatedResponse[Standings].model_validate(response.json()),
            force_refresh=force_refresh,
        )

    def get_lineups(self, match_id: int, *, force_refresh: bool = False) -> Lineups:
        """Fetch both teams' lineups for a match.

        Never cached (see ``DEFAULT_CACHE_TTLS``): per the docs, lineups
        "should be queried up to a few hours before the game starts" --
        exactly the window in which they're still being finalized.
        """
        return self._cached_request(
            "get_lineups",
            "GET",
            f"/lineups/{match_id}",
            {},
            lambda response: Lineups.model_validate(response.json()),
            force_refresh=force_refresh,
        )

    def get_box_score(self, match_id: int, *, force_refresh: bool = False) -> BoxScoreResult:
        """Fetch both teams' box scores for a match.

        The raw API response is an unlabeled ``[homeTeam, awayTeam]`` array
        (each element further wrapped in a ``"team"`` key -- see
        ``BoxScoreResult``'s docstring); this unwraps both into the named
        ``.home``/``.away`` result rather than exposing that raw shape.

        Raises ``HighlightlyNotFoundError`` if ``match_id``'s box score
        hasn't been published at all (an empty array), or
        ``HighlightlyResponseError`` if the array has any length other than
        the expected 2 -- e.g. exactly one team's box score being available
        (a realistic partial-data case, distinct from "not found": some
        data exists, just not the complete pair this method promises).

        Never cached (see ``DEFAULT_CACHE_TTLS``): docs say box scores
        refresh "every minute."
        """

        def parse(response: httpx.Response) -> BoxScoreResult:
            items = response.json()
            if not items:
                raise HighlightlyNotFoundError(
                    f"No box score found for match_id={match_id}",
                    url=str(response.request.url),
                    response_body=response.text,
                    resource_id=match_id,
                )
            if len(items) != 2:
                raise HighlightlyResponseError(
                    "Expected 2 elements (home and away) in box score "
                    f"response for match_id={match_id}, got {len(items)}",
                    url=str(response.request.url),
                    response_body=response.text,
                )
            home_raw, away_raw = items
            return BoxScoreResult(
                home=TeamBoxScore.model_validate(home_raw["team"]),
                away=TeamBoxScore.model_validate(away_raw["team"]),
            )

        return self._cached_request(
            "get_box_score",
            "GET",
            f"/box-score/{match_id}",
            {},
            parse,
            force_refresh=force_refresh,
        )

    def get_last_five_games(self, team_id: int, *, force_refresh: bool = False) -> list[Match]:
        """Fetch a team's five most recently completed matches.

        Cached for 15 minutes by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        return self._cached_request(
            "get_last_five_games",
            "GET",
            "/last-five-games",
            {"teamId": team_id},
            lambda response: [Match.model_validate(item) for item in response.json()],
            force_refresh=force_refresh,
        )

    def get_head_to_head(
        self, team_id_one: int, team_id_two: int, *, force_refresh: bool = False
    ) -> list[Match]:
        """Fetch the match history between two teams.

        Cached for 15 minutes by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        return self._cached_request(
            "get_head_to_head",
            "GET",
            "/head-2-head",
            {"teamIdOne": team_id_one, "teamIdTwo": team_id_two},
            lambda response: [Match.model_validate(item) for item in response.json()],
            force_refresh=force_refresh,
        )

    def get_players(
        self,
        name: str | None = None,
        limit: int = 1000,
        offset: int = 0,
        *,
        force_refresh: bool = False,
    ) -> PaginatedResponse[Player]:
        """List players matching the given filters.

        Unlike ``get_matches``/``get_highlights``, this endpoint accepts a
        zero-filter call per its docs -- no primary-parameter requirement
        applies here, so no client-side validation is added.

        Cached for 6 hours by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if name is not None:
            params["name"] = name

        return self._cached_request(
            "get_players",
            "GET",
            "/players",
            params,
            lambda response: PaginatedResponse[Player].model_validate(response.json()),
            force_refresh=force_refresh,
        )

    def get_player(self, player_id: int, *, force_refresh: bool = False) -> PlayerSummary:
        """Fetch a single player's profile by id.

        Raises ``HighlightlyNotFoundError`` if ``player_id`` doesn't exist.

        Cached for 6 hours by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        return self._cached_request(
            "get_player",
            "GET",
            f"/players/{player_id}",
            {},
            lambda response: PlayerSummary.model_validate(
                _first_or_not_found(response, resource="player", resource_id=player_id)
            ),
            force_refresh=force_refresh,
        )

    def get_player_statistics(
        self, player_id: int, *, force_refresh: bool = False
    ) -> PlayerStatistics:
        """Fetch a single player's season-by-season statistics by id.

        Raises ``HighlightlyNotFoundError`` if ``player_id`` doesn't exist.

        Cached for 6 hours by default (see ``DEFAULT_CACHE_TTLS``); pass
        ``force_refresh=True`` to bypass a cached result for this call.
        """
        return self._cached_request(
            "get_player_statistics",
            "GET",
            f"/players/{player_id}/statistics",
            {},
            lambda response: PlayerStatistics.model_validate(
                _first_or_not_found(response, resource="player", resource_id=player_id)
            ),
            force_refresh=force_refresh,
        )

    def get_highlights(
        self,
        league_name: str | None = None,
        date: str | date | None = None,
        season: int | None = None,
        match_id: int | None = None,
        home_team_id: int | None = None,
        away_team_id: int | None = None,
        home_team_name: str | None = None,
        away_team_name: str | None = None,
        home_team_abbreviation: str | None = None,
        away_team_abbreviation: str | None = None,
        home_team_display_name: str | None = None,
        away_team_display_name: str | None = None,
        limit: int = 40,
        offset: int = 0,
        *,
        force_refresh: bool = False,
    ) -> PaginatedResponse[Highlight]:
        """Fetch one page of highlight clips matching the given filters.

        ``date`` accepts either a string already in "YYYY-MM-DD" format or
        a ``datetime.date`` (formatted internally) -- the same dual-type
        acceptance as ``get_team_statistics``' ``from_date``, for the same
        reason: an Airflow ``{{ ds }}`` template renders as a string in
        that exact format, while a plain ``date`` object is also accepted
        for direct use. A string not already in that format raises
        ``ValueError`` rather than being sent to the API as-is -- a
        malformed date was previously sent through unvalidated, spending a
        real request on a call guaranteed to fail.

        Highlightly's docs state: "At least one primary query parameter
        needs to be specified before you can retrieve the data" for this
        endpoint (``timezone``/``limit``/``offset`` don't count). That's
        checked client-side before the network call, so a call missing
        every primary filter fails fast with ``ValueError`` instead of
        spending a request on a call the API is documented to reject.

        Note: a live check while building this method found the API
        currently accepts a zero-primary-param call for this endpoint
        anyway (returns 200, not the documented 400) -- but that's
        undocumented leniency, not a guarantee, so this validation matches
        the *documented* contract rather than today's observed behavior.

        **Known limitation 1: NFL highlight content appears sparse or absent
        on the free tier.** ``NFLClient().get_highlights(...)`` may return
        an empty page even for filters that clearly should match something.
        This was investigated directly: querying this endpoint with
        ``matchId`` set to a real, currently-scheduled NFL match's id (taken
        from a working ``league="NFL"`` match lookup) and no other filter
        still returned zero results, meaning there's no highlight content
        indexed for that match at all -- not a filtering problem. This is
        not fixable by choosing a different ``default_league`` value -- if
        this is empty for NFL, that's very likely genuine data sparsity on
        Highlightly's side, not a bug in this client.

        **Known limitation 2 (separate from the above): ``leagueName``'s
        filtering reliability is unconfirmed, independent of whether there's
        currently content to filter for.** ``leagueName="National Football
        Conference"`` was observed returning NCAA matches -- i.e. the filter
        may not reliably scope results to the requested league at all, as
        distinct from there being nothing to return. This matters even once
        real NFL highlight content exists later in the season: a caller
        could get incorrectly-scoped results rather than just an empty
        response. Until this is investigated further with real in-season
        data, don't trust ``get_highlights()`` results to be correctly
        pre-filtered by ``leagueName`` alone -- spot-check the returned
        ``Highlight.match`` (or team) fields against what you asked for.

        Never cached (see ``DEFAULT_CACHE_TTLS``): docs say highlights
        refresh "once a minute."
        """
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if date is not None:
            params["date"] = _format_from_date(date)
        if season is not None:
            params["season"] = season
        if match_id is not None:
            params["matchId"] = match_id
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
        params = self._with_default(params, "leagueName", league_name or self.default_league)
        self._require_at_least_one(params, {"timezone", "limit", "offset"}, "get_highlights")

        return self._cached_request(
            "get_highlights",
            "GET",
            "/highlights",
            params,
            lambda response: PaginatedResponse[Highlight].model_validate(response.json()),
            force_refresh=force_refresh,
        )

    def get_highlight(self, highlight_id: int, *, force_refresh: bool = False) -> Highlight:
        """Fetch a single highlight clip by id.

        Raises ``HighlightlyNotFoundError`` if ``highlight_id`` doesn't exist.

        Not in ``DEFAULT_CACHE_TTLS`` (uncached): a single highlight's own
        metadata is static once published, but there's no documented
        refresh cadence for this specific lookup and it's cheap/rare enough
        to call that caching it isn't worth the complexity here.
        """
        return self._cached_request(
            "get_highlight",
            "GET",
            f"/highlights/{highlight_id}",
            {},
            lambda response: Highlight.model_validate(
                _first_or_not_found(response, resource="highlight", resource_id=highlight_id)
            ),
            force_refresh=force_refresh,
        )
