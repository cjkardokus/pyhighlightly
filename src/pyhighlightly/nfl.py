"""NFL league client for Highlightly's American Football API.

Kept intentionally thin -- setting ``default_league`` is the only thing
that distinguishes this from ``AmericanFootballClient`` -- so it's obvious
what a future ``NCAAClient`` would look like.
"""

from __future__ import annotations

from pyhighlightly.american_football import AmericanFootballClient


class NFLClient(AmericanFootballClient):
    """Highlightly American Football client scoped to the NFL."""

    default_league: str | None = "NFL"
