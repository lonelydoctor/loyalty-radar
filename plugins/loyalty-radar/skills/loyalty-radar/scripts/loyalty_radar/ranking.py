"""Profile-aware ranking and diversity selection API."""

from .engine import rank_events, select_diverse_events

__all__ = ["rank_events", "select_diverse_events"]
