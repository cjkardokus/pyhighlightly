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
