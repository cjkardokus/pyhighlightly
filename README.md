# pyhighlightly

A typed Python client for [Highlightly](https://highlightly.net/)'s NFL API,
covering the free-tier endpoint surface.

`pyhighlightly` wraps Highlightly's American Football (NFL) REST API with
typed request/response models (via [pydantic](https://docs.pydantic.dev/))
and an [httpx](https://www.python-httpx.org/)-based client, so you can query
games, teams, players, and standings without hand-rolling request/response
parsing.

> **Status:** early scaffold. No client logic is implemented yet — see
> [Scope](#scope) and the project roadmap for what's coming.

## Installation

Once published to PyPI:

```bash
pip install pyhighlightly
```

or, with [uv](https://docs.astral.sh/uv/):

```bash
uv add pyhighlightly
```

## Scope

This client covers only Highlightly's **American Football (NFL) free-tier**
endpoints. Odds, bookmakers, and geo-restricted endpoints are intentionally
**out of scope**, since Highlightly's Basic/Free plan does not have access to
them. If you're on a paid Highlightly plan and need those endpoints, this
library is not (currently) the right fit.

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

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency management
and [hatchling](https://hatch.pypa.io/) as the build backend.

```bash
uv sync --all-extras --dev

uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
