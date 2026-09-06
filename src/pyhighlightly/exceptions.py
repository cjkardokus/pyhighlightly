"""Exception types raised by the pyhighlightly client.

These are sport-agnostic: they're raised by ``HighlightlyBaseClient`` and
therefore apply to every Highlightly sport client built on top of it.
"""

from __future__ import annotations

from datetime import datetime

#: Cap on how much of a response body an exception holds onto -- see
#: ``_truncate_response_body``.
_RESPONSE_BODY_TRUNCATE_AT = 2048


def _truncate_response_body(body: str | None) -> str | None:
    """Cap ``body`` at ``_RESPONSE_BODY_TRUNCATE_AT`` characters.

    A large HTML error page (a CDN outage page, a maintenance screen) would
    otherwise be held for the exception's entire lifetime and printed in
    full into any traceback that includes it. ``None`` passes through
    unchanged -- there's nothing to truncate when no body was captured.
    """
    if body is None or len(body) <= _RESPONSE_BODY_TRUNCATE_AT:
        return body
    return f"{body[:_RESPONSE_BODY_TRUNCATE_AT]}...[truncated, {len(body)} bytes total]"


class HighlightlyError(Exception):
    """Base class for all errors raised by pyhighlightly.

    Carries ``status_code``, ``url``, and ``response_body`` directly on the
    base class -- each defaulting to ``None`` -- so
    ``except HighlightlyError as e: e.status_code`` works uniformly
    regardless of which subclass was actually raised, without a caller
    needing ``getattr(e, "status_code", None)``. Not every raise site
    populates every field (a local rate-limit preemption has no
    ``status_code`` or ``response_body`` at all, since no request was ever
    sent -- see ``HighlightlyRateLimitError``), but the attributes always
    exist and default to ``None`` rather than being absent.

    ``response_body`` is truncated (see ``_truncate_response_body``)
    wherever it's populated, so a large error page doesn't get held for the
    exception's lifetime.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        url: str | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.url = url
        self.response_body = _truncate_response_body(response_body)


class HighlightlyAuthError(HighlightlyError):
    """Raised when the API rejects the request's credentials (401/403).

    ``response_body`` is worth inspecting specifically for this error:
    Highlightly's body text often distinguishes an invalid key from a valid
    key on the wrong plan (or hitting a geo-restricted endpoint), which is
    the single most useful debugging signal for this error type.
    """


class HighlightlyNotFoundError(HighlightlyError):
    """Raised when the requested resource does not exist.

    Two distinct triggers share this type: a real 404 response (``url``
    and ``response_body`` come from that response), and an endpoint that
    returns 200 with an empty single-resource array -- Highlightly's other
    way of saying "doesn't exist," used by e.g. ``get_team(id)`` for an id
    that isn't real (see ``AmericanFootballClient``). ``status_code``
    defaults to ``404`` since that covers the first case; for the second,
    the response actually was a 200, so ``status_code`` in that case
    reflects "the status this error models," not the underlying response's
    real status.

    ``resource_id`` is the id that was looked up and not found, when one
    exists -- for a call like ``get_team(5)``, that's ``5`` -- so a caller
    several stack frames away from the original call doesn't have to parse
    it back out of the message.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = 404,
        url: str | None = None,
        response_body: str | None = None,
        resource_id: int | str | None = None,
    ) -> None:
        """``status_code`` defaults to 404 -- see the class docstring for
        the one case (an empty-array 200) where that's a modeled status
        rather than the response's real one."""
        super().__init__(message, status_code=status_code, url=url, response_body=response_body)
        self.resource_id = resource_id


class HighlightlyRateLimitError(HighlightlyError):
    """Raised when the API rate limit has been (or was already) hit.

    This covers both an explicit 429 response from the API, and the client
    proactively refusing to make a new request because a previous response
    reported ``requests_remaining == 0``. ``preempted`` tells these two
    cases apart programmatically: ``True`` for the local, no-network-call
    case; ``False`` for a real 429. ``status_code`` is ``429`` for the
    latter and ``None`` for the former, since no request was ever sent.

    ``retry_at`` is populated only for the preempted case: computed from
    the client's local re-sync window (see the rate-limiting note on
    ``HighlightlyBaseClient``), it's the exact time this client will next
    let a real request through, which the API itself never advertises. A
    real 429's ``retry_after`` (seconds, from the response header when
    present) is the closest equivalent for that case.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        requests_remaining: int | None = None,
        status_code: int | None = None,
        url: str | None = None,
        response_body: str | None = None,
        preempted: bool = False,
        retry_at: datetime | None = None,
    ) -> None:
        """``retry_after``/``requests_remaining`` are ``None`` when the API
        response didn't include them, or when preempted locally without a
        network call at all. See the class docstring for ``preempted`` and
        ``retry_at``."""
        super().__init__(message, status_code=status_code, url=url, response_body=response_body)
        self.retry_after = retry_after
        self.requests_remaining = requests_remaining
        self.preempted = preempted
        self.retry_at = retry_at


class HighlightlyAPIError(HighlightlyError):
    """Catch-all for other 4xx/5xx responses from the API.

    Carries the raw status code, URL, and response body to aid debugging.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        response_body: str,
        url: str | None = None,
    ) -> None:
        """``response_body`` is the raw, unparsed response text (truncated --
        see ``HighlightlyError``)."""
        super().__init__(message, status_code=status_code, url=url, response_body=response_body)


class HighlightlyResponseError(HighlightlyError):
    """Raised when a successful-looking response can't be turned into the
    data an endpoint promises.

    Two causes share this type: a pydantic ``ValidationError`` (the API
    returned a shape that doesn't match this library's models -- schema
    drift on Highlightly's side) and a ``json.JSONDecodeError`` (the
    response wasn't JSON at all, e.g. an HTML maintenance page served with
    a 200 status). Either way, the original exception is chained via
    ``raise ... from exc`` and stays inspectable as ``__cause__`` -- this
    type exists so a caller can catch one ``HighlightlyError`` subclass
    uniformly, not to hide what actually went wrong underneath it.
    """
