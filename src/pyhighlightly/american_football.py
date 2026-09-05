"""American Football sport client for Highlightly.

``AmericanFootballClient`` points ``HighlightlyBaseClient`` at Highlightly's
American Football API host. It is itself a public extension point: it
implements no endpoint methods (those are deferred to a later branch,
alongside their response models), but establishes the shape that
league-specific clients -- ``NFLClient``, and eventually something like an
``NCAAClient`` -- build on.
"""

from __future__ import annotations

from typing import Any

from pyhighlightly.client import HighlightlyBaseClient

#: Param keys that already specify a league; if any of these is present,
#: ``_with_league_default`` leaves the caller's params untouched.
_LEAGUE_PARAM_KEYS = ("league", "leagueType", "leagueName")


class AmericanFootballClient(HighlightlyBaseClient):
    """Highlightly client for the American Football product surface.

    Subclasses set ``default_league`` to scope every request to a single
    league (see ``NFLClient``); left as ``None`` here since the base
    American Football client isn't tied to any one league.
    """

    base_url: str | None = "https://american-football.highlightly.net"
    default_league: str | None = None

    def _with_league_default(self, params: dict[str, Any]) -> dict[str, Any]:
        """Inject ``default_league`` into ``params`` unless already present.

        Returns ``params`` unchanged if there's no default league configured,
        or if the caller already passed a ``league``/``leagueType``/
        ``leagueName`` key explicitly.
        """
        if self.default_league is None:
            return params
        if any(key in params for key in _LEAGUE_PARAM_KEYS):
            return params
        return {**params, "league": self.default_league}
