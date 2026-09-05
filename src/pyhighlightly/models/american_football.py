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

from pydantic import BaseModel, Field


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
