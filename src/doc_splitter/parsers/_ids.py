"""Stable element ID generation."""

from __future__ import annotations


def next_element_id(counter: int) -> tuple[str, int]:
    counter += 1
    return f"el-{counter:03d}", counter