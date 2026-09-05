"""pyhighlightly: a typed Python client for Highlightly's sport APIs.

``HighlightlyBaseClient`` and ``AmericanFootballClient`` are public
extension points, not just internal plumbing: they're the base classes for
building a client against any other Highlightly sport (basketball, soccer,
hockey, ...) or additional American Football leagues beyond the NFL.

This package currently ships endpoint coverage for Highlightly's American
Football (NFL) free tier only. See the project README for scope details.
"""

from pyhighlightly.american_football import AmericanFootballClient
from pyhighlightly.client import HighlightlyBaseClient
from pyhighlightly.exceptions import (
    HighlightlyAPIError,
    HighlightlyAuthError,
    HighlightlyError,
    HighlightlyNotFoundError,
    HighlightlyRateLimitError,
)
from pyhighlightly.nfl import NFLClient

__all__ = [
    "AmericanFootballClient",
    "HighlightlyAPIError",
    "HighlightlyAuthError",
    "HighlightlyBaseClient",
    "HighlightlyError",
    "HighlightlyNotFoundError",
    "HighlightlyRateLimitError",
    "NFLClient",
]
