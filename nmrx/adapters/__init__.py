"""Declarative source adapters: a plan (routes + field mapping) plus a mapping engine."""

from .base import (
    AdapterError,
    AdapterPlan,
    Route,
    SchemaUnconfirmed,
    SourceAdapter,
    available_plans,
    map_payload,
)

__all__ = [
    "AdapterError", "AdapterPlan", "Route", "SchemaUnconfirmed",
    "SourceAdapter", "available_plans", "map_payload",
]
