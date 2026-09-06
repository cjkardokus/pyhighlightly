"""American Football resource models.

These mirror Highlightly's NFL/NCAA API response shapes as closely as
possible -- field names, casing, and enum string values match what the API
actually returns (see https://highlightly.net/nfl-api/documentation/),
rather than being renamed or restructured for "nicer" Python conventions.
Fidelity to the source API is a deliberate design goal of this client: if a
field looks oddly named or typed (e.g. ``Score`` fields being strings like
``"21 - 7"`` rather than parsed ints, or ``Forecast.temperature`` being a
string like ``"11.97°C"``), that's the API, not an oversight here.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator


class MatchState(str, Enum):
    """The known values of ``MatchStateInfo.description``.

    Not used as a field type directly (``description`` stays a plain
    ``str`` so an unrecognized future value from the API doesn't break
    parsing) -- this is exported so callers can compare against it, e.g.
    ``match.state.description == MatchState.FINISHED``.
    """

    SCHEDULED = "Scheduled"
    IN_PROGRESS = "In progress"
    HALF_TIME = "Half time"
    END_PERIOD = "End period"
    SUSPENDED = "Suspended"
    POSTPONED = "Postponed"
    CANCELLED = "Cancelled"
    ABANDONED = "Abandoned"
    FINISHED = "Finished"
    UNKNOWN = "Unknown"


class Team(BaseModel):
    """A team, as returned by ``/teams`` and nested in match responses."""

    id: int
    logo: str
    name: str
    displayName: str
    abbreviation: str
    #: Not present on every endpoint that nests a ``Team`` (e.g. absent from
    #: ``Match.homeTeam``/``awayTeam``, present on ``Injury.team``).
    league: str | None = None


class Score(BaseModel):
    """A match's score, per period.

    Every field is a string in the API's own ``"<away> - <home>"`` (or
    similar) format, e.g. ``"21 - 7"`` -- deliberately not parsed into ints
    here, to match the API exactly rather than assume a fixed order. Any
    period can come back ``null`` for a period that hasn't happened yet
    (a scheduled game, or a game that never went to overtime), confirmed
    against live API responses -- so every field is optional.
    """

    current: str | None = None
    firstPeriod: str | None = None
    secondPeriod: str | None = None
    thirdPeriod: str | None = None
    fourthPeriod: str | None = None
    firstOvertimePeriod: str | None = None
    secondOvertimePeriod: str | None = None


class MatchStateInfo(BaseModel):
    """The live/final state of a match, as nested under ``Match.state``."""

    period: int
    #: An elapsed-time clock. Seen as a plain int (seconds/minutes) on
    #: ``Match.state`` and as a "MM:SS" string within ``MatchEvent`` markers.
    clock: int | str
    description: str
    score: Score
    report: str | None = None


class Match(BaseModel):
    """One match, as returned in the paginated list from ``get_matches()``.

    Use ``MatchDetail`` (via ``get_match(id)``) for full per-game data
    including venue, injuries, play-by-play, and predictions.
    """

    id: int
    round: str
    date: datetime
    league: str
    season: int
    awayTeam: Team
    homeTeam: Team
    state: MatchStateInfo


class Venue(BaseModel):
    """Where a match is played."""

    name: str | None = None
    city: str | None = None
    state: str | None = None


class Forecast(BaseModel):
    """Weather forecast for a match.

    ``temperature`` is a string including its unit (e.g. ``"11.97°C"``), as
    returned by the API -- not parsed into a number.
    """

    status: str | None = None
    temperature: str | None = None


class TeamStatistic(BaseModel):
    """One named statistic value, as nested under ``MatchStatistics``."""

    name: str
    value: int | float | str


class MatchTeamStatistics(BaseModel):
    """One side's statistics within a match's ``MatchStatistics``."""

    statistics: list[TeamStatistic]


class MatchStatistics(BaseModel):
    """Per-team statistics for a single match."""

    homeTeam: MatchTeamStatistics
    awayTeam: MatchTeamStatistics


class InjuryPlayer(BaseModel):
    """A player referenced in an ``Injury`` entry."""

    name: str
    jersey: int
    position: str


class InjuryEntry(BaseModel):
    """One player's injury status, as nested under ``Injury.data``."""

    status: str
    player: InjuryPlayer


class Injury(BaseModel):
    """A team's reported injuries for a match."""

    team: Team
    data: list[InjuryEntry]


class MatchEventMarker(BaseModel):
    """The clock/period/field-position at the start or end of a ``MatchEvent``.

    ``clock`` has been observed ``null`` on live responses (e.g. the end
    marker of a half-ending event), so it's optional despite always being a
    string when present.
    """

    clock: str | None = None
    period: str
    yardLine: int


class PlayPosition(BaseModel):
    """Down-and-distance/field-position at the start or end of a ``PlayDetail``."""

    down: int
    distance: int
    yardLine: int
    yardsToEndzone: int
    possessionText: str


class PlayDetail(BaseModel):
    """One individual play within a ``MatchEvent``."""

    start: PlayPosition
    end: PlayPosition
    text: str
    type: str
    period: int
    clock: str
    isPenalty: bool


class MatchEvent(BaseModel):
    """One drive/event of play-by-play data within a ``MatchDetail``.

    ``playDetails`` is documented by the API but has been observed absent
    entirely on live responses (not just empty) -- it defaults to an empty
    list rather than being required.
    """

    start: MatchEventMarker
    end: MatchEventMarker
    team: Team
    plays: list[str]
    playDetails: list[PlayDetail] = Field(default_factory=list)
    result: str
    description: str
    isScoringPlay: bool


class PredictionProbabilities(BaseModel):
    """Win/draw probabilities for a ``Prediction``, as percentage strings."""

    home: str
    draw: str
    away: str


class Prediction(BaseModel):
    """One model's prediction for a match."""

    type: str
    modelType: str
    generatedAt: datetime
    description: str
    probabilities: PredictionProbabilities


class Predictions(BaseModel):
    """All predictions for a match, grouped by when they were generated."""

    prematch: list[Prediction] = Field(default_factory=list)
    live: list[Prediction] = Field(default_factory=list)


class MatchDetail(Match):
    """Full detail for a single match, returned by ``get_match(id)``.

    Extends ``Match`` with the additional fields only available when
    querying a specific match by id. These are all optional: some (e.g.
    ``matchStatistics``, ``predictions``) may genuinely be absent for a
    match that hasn't started yet or has no odds/stats coverage.
    """

    venue: Venue | None = None
    forecast: Forecast | None = None
    matchStatistics: MatchStatistics | None = None
    injuries: list[Injury] = Field(default_factory=list)
    events: list[MatchEvent] = Field(default_factory=list)
    predictions: Predictions | None = None


class TeamStatisticsGames(BaseModel):
    """Win/loss record, as nested under a ``TeamStatisticsSplit``."""

    played: int
    wins: int
    loses: int


class TeamStatisticsPoints(BaseModel):
    """Points scored/allowed, as nested under a ``TeamStatisticsSplit``."""

    scored: int
    received: int


class TeamStatisticsSplit(BaseModel):
    """A team's record and scoring for one split (total/home/away)."""

    games: TeamStatisticsGames
    points: TeamStatisticsPoints


class TeamStatistics(BaseModel):
    """A team's season statistics, as returned by ``get_team_statistics()``."""

    total: TeamStatisticsSplit
    home: TeamStatisticsSplit
    away: TeamStatisticsSplit
    leagueName: str
    round: str


class StandingsStatistic(BaseModel):
    """One named standings figure, e.g. ``{"value": "+55", "displayName":
    "Point Differential"}``.

    Distinct from ``TeamStatistic``/``BoxScoreStatistic``, which use a
    different ``{group, name, value}`` shape -- standings figures are always
    pre-formatted display strings (win percentages, streaks like ``"W3"``,
    "-" for not-applicable), never raw numbers.
    """

    value: str
    displayName: str


class StandingsEntry(BaseModel):
    """One team's row within a ``Standings`` group."""

    team: Team
    statistics: list[StandingsStatistic]


class Standings(BaseModel):
    """One standings group: a single conference's table for one season type.

    Returned by ``get_standings()`` as ``PaginatedResponse[Standings]``, not
    as a single object: a real response contains one ``Standings`` entry per
    (conference, season type) combination matching the query -- e.g.
    querying ``leagueType="NFL"`` for a given year returns six of these
    (AFC/NFC x Preseason/Regular Season/Postseason), each with its own
    ``data`` list of team rows. This *does* carry the usual
    ``pagination``/``plan`` envelope, confirmed against a live response --
    unlike ``/teams``, this endpoint's ``limit``/``offset`` params are real
    pagination over these groups, not a red herring.
    """

    leagueName: str
    abbreviation: str
    year: int
    leagueType: str
    seasonType: str
    startDate: datetime
    endDate: datetime
    data: list[StandingsEntry]


class LineupPlayer(BaseModel):
    """One player within a ``TeamLineup``."""

    id: int
    jersey: int
    player: str
    position: str
    positionAbbreviation: str
    isStarter: bool


class TeamLineup(BaseModel):
    """One side's lineup, as nested under ``Lineups``."""

    team: Team
    lineup: list[LineupPlayer]


class Lineups(BaseModel):
    """Both teams' lineups for a match, as returned by ``get_lineups()``."""

    home: TeamLineup
    away: TeamLineup


class BoxScorePlayer(BaseModel):
    """A player referenced in a ``PlayerBoxScore``.

    ``jersey`` has been observed ``null`` on live responses (e.g. for a
    player who didn't dress), despite the docs showing it as always present.
    """

    id: int
    name: str
    jersey: int | None = None


class BoxScoreStatistic(BaseModel):
    """One named box-score figure, e.g. ``{"group": "Passing", "name":
    "Total Passing Yards", "value": 221}``.

    ``value`` is genuinely loosely typed per the API docs -- a stat can be
    numeric, a formatted string, or null/absent -- so it's deliberately not
    coerced to a single numeric type here.
    """

    group: str
    name: str
    value: int | float | str | None = None


class PlayerBoxScore(BaseModel):
    """One player's box-score line, as nested under ``TeamBoxScore``."""

    player: BoxScorePlayer
    statistics: list[BoxScoreStatistic]


class TeamBoxScore(BaseModel):
    """One team's box score, as returned (nested) by ``get_box_score()``."""

    id: int
    name: str
    logo: str | None = None
    boxScores: list[PlayerBoxScore]


class BoxScoreResult(BaseModel):
    """Both teams' box scores for a match, as returned by ``get_box_score()``.

    The raw API response is an unlabeled two-element array,
    ``[{"team": {...home box score...}}, {"team": {...away box score...}}]``
    -- confirmed against a live response, including the extra ``"team"``
    wrapper around each element that isn't mentioned in the written docs.
    This model exists specifically so callers get ``.home``/``.away``
    instead of index-based access into that array: a deliberate, documented
    exception to this client's usual fidelity-to-source-shape approach,
    since an unlabeled positional pair is exactly the kind of thing that's
    easy to get backwards at a call site.
    """

    home: TeamBoxScore
    away: TeamBoxScore


class HighlightType(str, Enum):
    """Whether a highlight clip has been manually verified by Highlightly."""

    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"


class HighlightCategory(str, Enum):
    """The kind of play or content a ``Highlight`` clip covers."""

    MATCH_HIGHLIGHTS = "match-highlights"
    TOUCHDOWN_PASS = "touchdown-pass"
    TOUCHDOWN_RUSH = "touchdown-rush"
    TOUCHDOWN_RECEPTION = "touchdown-reception"
    TOUCHDOWN = "touchdown"
    INTERCEPTION = "interception"
    INTERCEPTION_RETURN_TD = "interception-return-td"
    FUMBLE = "fumble"
    FUMBLE_RECOVERY_TD = "fumble-recovery-td"
    SACK = "sack"
    FIELD_GOAL = "field-goal"
    SAFETY = "safety"
    SPECIAL_TEAMS_PLAY = "special-teams-play"
    SPECIAL_TEAMS_TD = "special-teams-td"
    TWO_POINT_CONVERSION = "two-point-conversion"
    PENALTY = "penalty"
    BIG_PLAY = "big-play"
    DEFENSIVE_PLAY = "defensive-play"
    VIRAL_MOMENT = "viral-moment"
    INJURY = "injury"
    PRE_MATCH_CONTENT = "pre-match-content"
    POST_MATCH_CONTENT = "post-match-content"
    OTHER = "other"


class HighlightMatch(BaseModel):
    """The match info embedded in a ``Highlight``.

    Deliberately a separate model from ``Match``, not a reuse of it: a live
    response confirmed a highlight's nested ``match`` object never includes
    ``state`` (checked across ten highlights spanning both pre-match and
    post-match content), so validating it against ``Match`` -- which
    requires ``state`` -- would fail on every real highlight response.
    """

    id: int
    round: str
    date: datetime
    league: str
    season: int
    awayTeam: Team
    homeTeam: Team


class Highlight(BaseModel):
    """A highlight clip, as returned by ``get_highlights()``/``get_highlight()``."""

    id: int
    type: HighlightType
    imgUrl: str
    title: str
    description: str | None = None
    url: str
    embedUrl: str | None = None
    match: HighlightMatch
    channel: str | None = None
    source: str
    category: HighlightCategory

    @field_validator("category", mode="before")
    @classmethod
    def _fall_back_to_other_for_unknown_categories(cls, value: object) -> object:
        """Coerce an unrecognized category value to ``OTHER`` instead of
        raising.

        Highlightly's docs say unrecognized clips are already labeled
        "other" on their side, but this taxonomy is actively growing --
        new category strings are plausible over time. A published client
        library shouldn't hard-crash on every new category Highlightly
        adds until someone updates this enum; falling back to ``OTHER`` is
        deliberate, documented, forward-compatible behavior, not a gap.
        """
        try:
            HighlightCategory(value)
        except ValueError:
            return HighlightCategory.OTHER
        return value


class Player(BaseModel):
    """A player, as returned by ``get_players()``."""

    id: int
    fullName: str
    logo: str | None = None


class Draft(BaseModel):
    """A player's draft position, as nested under ``PlayerProfile``."""

    round: int
    year: int
    pick: int


class PlayerPosition(BaseModel):
    """A player's position, as nested under ``PlayerProfile``."""

    main: str
    abbreviation: str


class PlayerProfile(BaseModel):
    """A player's biographical/roster info, as nested under ``PlayerSummary``.

    ``jersey``, ``height``, and ``weight`` are strings (e.g. ``"12"``,
    ``"6' 4\\""``, ``"225 lbs"``), confirmed against a live response --
    not parsed into numbers, matching the API exactly.
    """

    fullName: str
    birthPlace: str
    birthDate: str
    height: str
    jersey: str
    weight: str
    isActive: bool
    position: PlayerPosition
    draft: Draft | None = None
    team: Team


class PlayerSummary(Player):
    """Full detail for a single player, returned by ``get_player(id)``.

    Extends ``Player`` with the additional ``profile`` field only available
    when querying a specific player by id -- same pattern as
    ``Match``/``MatchDetail``.
    """

    profile: PlayerProfile


class PlayerStat(BaseModel):
    """One named statistic value, as nested under ``PlayerSeasonStats``.

    ``value`` is loosely typed for the same reason as
    ``BoxScoreStatistic.value``: a stat can be numeric, a formatted string,
    or null, and forcing numeric coercion would break on the non-numeric
    ones.
    """

    name: str
    value: int | float | str | None = None
    category: str


class PlayerSeasonStats(BaseModel):
    """One season's worth of statistics, as nested under ``PlayerStatistics``."""

    stats: list[PlayerStat]
    teams: list[Team]
    league: str
    season: int
    #: "Entire" or "Season" per the docs -- plain ``str`` rather than an
    #: enum, since (unlike the actively-growing highlight categories) this
    #: is a stable two-value field with no real forward-compat concern.
    seasonBreakdown: str


class PlayerStatistics(Player):
    """Full season-by-season statistics for a player, returned by
    ``get_player_statistics(id)``.
    """

    perSeason: list[PlayerSeasonStats]
