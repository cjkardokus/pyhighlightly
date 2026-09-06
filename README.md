# pyhighlightly

A typed Python client for [Highlightly](https://highlightly.net/)'s NFL API,
covering the free-tier endpoint surface.

`pyhighlightly` wraps Highlightly's American Football (NFL) REST API with
typed request/response models (via [pydantic](https://docs.pydantic.dev/))
and an [httpx](https://www.python-httpx.org/)-based client, so you can query
games, teams, players, and standings without hand-rolling request/response
parsing.

> **Status:** pre-1.0 and under active development. Every free-tier NFL
> endpoint is implemented — teams, matches, standings, lineups, box scores,
> players, and highlights — with built-in rate-limit handling and response
> caching. Not yet published to PyPI; see [Installation](#installation).

## Scope

This client covers only Highlightly's **American Football (NFL) free-tier**
endpoints. Odds, bookmakers, and geo-restricted endpoints are intentionally
**out of scope**, since Highlightly's Basic/Free plan does not have access to
them. If you're on a paid Highlightly plan and need those endpoints, this
library is not (currently) the right fit.

## Installation

Not yet published to PyPI. Install directly from GitHub:

```bash
pip install git+https://github.com/cjkardokus/pyhighlightly.git
```

or, with [uv](https://docs.astral.sh/uv/):

```bash
uv add git+https://github.com/cjkardokus/pyhighlightly.git
```

PyPI publishing is planned but hasn't happened yet.

## Quickstart

```python
from pyhighlightly import NFLClient

client = NFLClient(api_key="YOUR_HIGHLIGHTLY_API_KEY")

teams = client.get_teams()
print(f"{len(teams)} NFL teams")
print(teams[0].displayName)

matches = client.get_matches(season=2024, limit=5)
for match in matches.data:
    print(match.date, match.awayTeam.displayName, "@", match.homeTeam.displayName)
```

`api_key` works with a key from either Highlightly's own platform or its
RapidAPI listing — see [Rate Limiting](#rate-limiting) below for how the two
differ. Every endpoint method returns typed pydantic models (or a
`PaginatedResponse` wrapping them), so your editor/type-checker knows the
shape of the response without you having to look it up.

## Extending this client

This client's class hierarchy is deliberately built to extend beyond the NFL:

- **`HighlightlyBaseClient`** (`client.py`) is fully generic and
  sport-agnostic — it knows nothing about American football specifically.
  It owns auth, rate-limit tracking, caching, and pagination, and is the
  base a client for any other Highlightly sport (basketball, soccer,
  hockey, ...) would extend.
- **`AmericanFootballClient`** (`american_football.py`) extends it with
  every American Football endpoint (teams, matches, standings, lineups, box
  scores, players, highlights) plus a `default_league` hook that
  league-specific subclasses set.
- **`NFLClient`** extends `AmericanFootballClient` and does nothing but set
  `default_league = "NFL"` — intentionally thin, as the template for what an
  `NCAAClient` would look like (not implemented yet, since this client's
  [current scope](#scope) is NFL-only).

A future NCAA client, for instance, would be as small as:

```python
class NCAAClient(AmericanFootballClient):
    default_league = "NCAA"
```

A client for a different sport entirely would subclass `HighlightlyBaseClient`
directly and implement its own endpoint methods, following the same shape as
`AmericanFootballClient`.

## Rate Limiting

Highlightly's free tier allows 100 requests/day. Highlightly is distributed
through RapidAPI, and per RapidAPI's platform documentation that quota resets
on a **rolling 24-hour window anchored to your subscription's timestamp**
(e.g. subscribed at 11:30:15 UTC → resets at 11:30:15 UTC every day after) —
not at a fixed clock time like midnight UTC, and Highlightly's API responses
don't include any reset-time header to check against (confirmed against a
live `/teams` response — only `x-ratelimit-requests-limit` and
`x-ratelimit-requests-remaining` are present). Because of that,
`HighlightlyBaseClient` preempts requests locally once it observes
`requests_remaining == 0` rather than sending a request it already expects to
be rejected — but it won't do so forever: it re-syncs with a real request
after 24 hours have passed since that zero was observed, since the actual
window has almost certainly rolled over by then. This matters for anything
long-lived (an Airflow-scheduled poller, a persistent worker) — see the
"Rate limiting" note on `HighlightlyBaseClient` in `client.py` for the full
details.

In practice, a reset at midnight UTC has now been confirmed twice,
independently, for a key issued directly through Highlightly's own platform:
on two separate days, the dashboard for that key reset to 0% at almost
exactly midnight UTC, and on the second occasion this project's own live
validation work made exactly 16 requests after that reset boundary
mid-session — which matched the dashboard's usage count exactly. This may
still not match the RapidAPI-marketplace behavior described above —
Highlightly's own docs say accounts aren't synced across the two platforms —
and two consistent observations are still not a documented guarantee from
Highlightly, so it could change without notice. The client doesn't assume
either mechanism; the re-sync logic above (`_zero_observed_at` and the
24-hour bounded re-sync) is unchanged and works the same regardless of which
applies.

## Caching

Caching is **on by default**. Every endpoint method has a sensible default
TTL based on how often Highlightly's own docs say that data actually
refreshes — see `AmericanFootballClient.DEFAULT_CACHE_TTLS` for the full
table and the reasoning behind each bucket. Roughly: static reference data
(teams, players) is cached for hours; data that updates on the order of
minutes-to-an-hour after a game (standings, team statistics, recent-game
lookups) is cached for 15–30 minutes; anything that can change while a game
is live (matches, a single match's detail, box scores, lineups, highlights)
is **never** cached, so you always see the current state of an in-progress
game.

```python
client.get_teams()  # network call
client.get_teams()  # served from cache, no network call

# Bypasses the cache read, refetches, and writes the fresh result back:
client.get_teams(force_refresh=True)
```

**Overriding TTLs.** Pass `cache_ttls` at construction to override specific
endpoints (by method name) without touching the rest:

```python
client = NFLClient(api_key="...", cache_ttls={"get_standings": 60})
```

A TTL of `0` means "never cache this endpoint," and is honored even if
caching is otherwise enabled.

**Swapping backends.** The default `InMemoryCache` lives in a single
process and isn't shared across workers. `CacheBackend` is a public
[`Protocol`](https://docs.python.org/3/library/typing.html#typing.Protocol)
extension point — pass any object implementing `get`/`set`/`delete` (a
Redis-backed cache, for example) as `cache=` to use it instead:

```python
client = NFLClient(api_key="...", cache=my_redis_backed_cache)
```

**Disabling caching entirely.** Pass `enable_cache=False` to turn off all
caching, regardless of `cache_ttls`:

```python
client = NFLClient(api_key="...", enable_cache=False)
```

## Known Limitations

- **NFL highlight content appears sparse or absent via `get_highlights()`
  on the free tier.** Investigated directly: querying `/highlights` with
  `matchId` set to a real, currently-scheduled NFL match's id and no other
  filter still returned zero results — there's no highlight content indexed
  for that match at all, not a filtering bug. So an empty page from
  `NFLClient().get_highlights()` is very likely genuine data sparsity on
  Highlightly's side, not a bug in this client — see the docstring on
  `get_highlights()` for the full investigation.

- **Separately, `leagueName`'s filtering reliability on `/highlights` is
  unconfirmed** — a different problem from the sparsity above, and one that
  stays relevant once real NFL highlight content exists later in the
  season. `leagueName="National Football Conference"` was observed
  returning NCAA matches, meaning the filter may not reliably scope results
  to the requested league at all: a caller could get incorrectly-scoped
  results, not just an empty response. Until this is investigated further
  with real in-season data, spot-check `get_highlights()` results against
  the returned match/team fields rather than trusting them to be correctly
  pre-filtered by `leagueName` alone.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management
and [hatchling](https://hatch.pypa.io/) as the build backend. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor workflow;
quick version:

```bash
uv sync

uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
