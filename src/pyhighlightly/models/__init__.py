"""Pydantic models for Highlightly API resources.

Sport-agnostic envelope models (``PaginatedResponse``, ``Pagination``,
``Plan``) live in ``pyhighlightly.models.common`` and are shared by any
Highlightly sport client. Sport-specific resource models live in their own
submodule, e.g. ``pyhighlightly.models.american_football``.
"""

from pyhighlightly.models.common import PaginatedResponse, Pagination, Plan

__all__ = ["PaginatedResponse", "Pagination", "Plan"]
