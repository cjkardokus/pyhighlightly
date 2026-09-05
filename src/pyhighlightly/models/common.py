"""Sport-agnostic response envelope models.

Every Highlightly API response (regardless of sport) wraps its results in
the same ``{data, pagination, plan}`` envelope, so these models are shared
by any Highlightly sport client, not just American Football.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Pagination(BaseModel):
    """Pagination metadata included in every paginated Highlightly response."""

    totalCount: int
    offset: int
    limit: int


class Plan(BaseModel):
    """Highlightly plan/tier metadata included in every response."""

    tier: str
    message: str


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic envelope wrapping a page of results from any Highlightly endpoint."""

    data: list[T]
    pagination: Pagination
    plan: Plan
