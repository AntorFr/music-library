"""Pins for code rewritten by the ruff-clean task (SIM110 any/all, hex colour check).

Each test fails if the rewritten condition is turned into a constant.
"""

from __future__ import annotations

import pytest

from app.schemas.media import SelectionFallback, TagFilter, TagQueryGroup
from app.services.select_engine import apply_fallback
from app.services.tag_service import _normalize_hex_color


@pytest.mark.parametrize("fallback", [SelectionFallback.soft, SelectionFallback.force])
def test_relaxing_fallback_never_returns_item_matching_none_of(fallback):
    items = ["a", "b", "c"]
    item_tags = [
        {"owner": {"papa"}, "genre": {"metal"}},  # excluded by none_of
        {"owner": {"maman"}},
        {"owner": {"maman"}, "genre": {"jazz"}},
    ]
    group = TagQueryGroup(
        all_of=[TagFilter(category="owner", values=["papa"])],
        any_of=[],
        none_of=[TagFilter(category="genre", values=["metal"])],
    )

    picked = apply_fallback(
        items=items,
        item_tags=item_tags,
        group=group,
        limit=3,
        fallback=fallback,
        include_order=["owner"],
    )

    assert 0 not in picked


def test_hex_color_rejects_seven_chars_with_non_hex_digit():
    with pytest.raises(ValueError):
        _normalize_hex_color("#12zz56")


def test_hex_color_accepts_and_lowercases_valid():
    assert _normalize_hex_color("#AbC123") == "#abc123"
