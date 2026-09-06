# Contributing to pyhighlightly

Thanks for your interest in contributing. This project is in a **pre-1.0,
actively-hardening phase** — expect some churn. Model fields, endpoint
signatures, and internal helpers may still change as more of Highlightly's
surface gets implemented and cross-checked against the live API. PRs are
welcome; for anything beyond a small fix, opening an issue first to talk
through the approach is appreciated, so you're not surprised by a design
disagreement after the fact.

## Dev environment

This project uses [uv](https://docs.astral.sh/uv/) for dependency management
and [hatchling](https://hatch.pypa.io/) as the build backend.

```bash
git clone https://github.com/cjkardokus/pyhighlightly.git
cd pyhighlightly
uv sync
```

`uv sync` installs the project along with its `dev` dependency group
(`ruff`, `mypy`, `pytest`, `respx` -- see `[dependency-groups]` in
`pyproject.toml`), which is included by default.

## Before submitting a PR

Run the full check suite locally — this is exactly what CI runs:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy .
uv run pytest
```

All four need to pass. `uv run ruff format .` (without `--check`) will fix
formatting issues for you; `ruff check --fix` handles some lint issues too,
but most `mypy`/`pytest` failures need a real fix.

## Adding a new endpoint

If you're adding coverage for a new Highlightly endpoint:

- Add the response model(s) to `src/pyhighlightly/models/american_football.py`
  (or the equivalent module, if you're building out a different sport).
- Add the endpoint method to `src/pyhighlightly/american_football.py` (or the
  relevant sport client), following the shape of the existing methods there:
  build `params` from the method's keyword arguments, apply any league
  defaulting via `self._with_default(...)`, and route the actual call
  through `self._cached_request(...)` rather than `self._request(...)`
  directly, so it participates in caching and rate-limit handling the same
  way every other endpoint does. Add a keyword-only `force_refresh: bool
  = False` parameter (`*, force_refresh: bool = False` in the signature —
  every endpoint method takes it this way, so a caller can't pass it
  positionally and a later filter argument inserted before it can't
  silently change what an existing positional call means) and a
  `DEFAULT_CACHE_TTLS` entry for it.
- **Validate against the live API, not just Highlightly's written docs**,
  before trusting a response shape. Several endpoints in this project's
  history turned out to differ from what the docs show — an undocumented
  wrapper key, a field that's `null` far more often than the docs imply, a
  path that doesn't match the one documented. See the docstrings on
  `Standings`, `BoxScoreResult`, and `HighlightMatch` (and the git history
  around them) for real examples of this. If you have a Highlightly API key,
  spend a handful of real requests confirming the shape rather than trusting
  the docs alone — and if you find a discrepancy, document it in the
  model/method's docstring the same way those do.
- Add respx-mocked tests covering the new method's parameter handling and
  response parsing, in `tests/test_american_football.py` (or `test_cache.py`
  / `test_client.py` for anything sport-agnostic).

## Branch convention

This client was built incrementally, one branch (and PR) per logical unit of
work — e.g. `feat/core-client`, `feat/team-and-match-endpoints`,
`feat/caching-layer`. That's a loose convention worth following for a
sizable change (easier to review, easier to bisect later if something
breaks), not a rigid rule — a small fix doesn't need a themed branch name of
its own.

## Questions

Open an issue if anything here is unclear or has gone stale.
