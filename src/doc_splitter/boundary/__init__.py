"""Boundary detection for conceptual document splitting.

Planner exports are loaded lazily so importing ``doc_splitter.topic_reviews`` does not
create a package initialization cycle through ``boundary.planner``.
"""

from __future__ import annotations

from doc_splitter.boundary.safe_candidates import find_safe_candidates

__all__ = [
    "commit_boundary",
    "find_safe_candidates",
    "get_boundary_context",
    "load_session",
    "save_session",
]


def __getattr__(name: str):
    if name in {"commit_boundary", "get_boundary_context", "load_session", "save_session"}:
        from doc_splitter.boundary import planner

        return getattr(planner, name)
    raise AttributeError(name)
