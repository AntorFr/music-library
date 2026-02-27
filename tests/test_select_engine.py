from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.schemas.media import SelectionFallback, TagFilter, TagQueryGroup
from app.services.select_engine import (
    apply_fallback,
    evaluate_group,
    parse_tag_filters_from_qsl,
)


@dataclass(frozen=True)
class Item:
    id: str
    ts: int


def test_parse_tag_filters_from_qsl_order_and_csv():
    pairs = [
        ("owner", "papa"),
        ("mood", "calm"),
        ("tag_style", "rock,pop"),
        ("not_tag_style", "metal"),
        ("not_mood", "angry"),
    ]

    parsed = parse_tag_filters_from_qsl(pairs, reserved_keys=set())

    assert parsed.include_order == ["owner", "mood", "style"]
    assert parsed.include_values["owner"] == {"papa"}
    assert parsed.include_values["style"] == {"rock", "pop"}
    assert parsed.exclude_values["style"] == {"metal"}
    assert parsed.exclude_values["mood"] == {"angry"}


def test_parse_tag_filters_normalizes_case_and_accents():
    pairs = [
        ("Owner", "Sébastien"),
        ("mood", "Calme"),
        ("time_of_day", "Soirée"),
    ]

    parsed = parse_tag_filters_from_qsl(pairs, reserved_keys=set())

    assert parsed.include_order == ["owner", "mood", "time_of_day"]
    assert parsed.include_values["owner"] == {"sebastien"}
    assert parsed.include_values["mood"] == {"calme"}
    assert parsed.include_values["time_of_day"] == {"soiree"}


def test_evaluate_group_nested_any_of_and_none_of():
    group = TagQueryGroup(
        all_of=[TagFilter(category="owner", values=["papa"])],
        any_of=[
            TagQueryGroup(all_of=[TagFilter(category="mood", values=["calm"])], any_of=[], none_of=[]),
            TagQueryGroup(all_of=[TagFilter(category="context", values=["evening"])], any_of=[], none_of=[]),
        ],
        none_of=[TagFilter(category="genre", values=["metal"])],
    )

    tags_ok = {
        "owner": {"papa"},
        "mood": {"calm"},
        "genre": {"jazz"},
    }
    assert evaluate_group(tags_ok, group) is True

    tags_ok2 = {
        "owner": {"papa"},
        "context": {"evening"},
    }
    assert evaluate_group(tags_ok2, group) is True

    tags_bad_excluded = {
        "owner": {"papa"},
        "mood": {"calm"},
        "genre": {"metal"},
    }
    assert evaluate_group(tags_bad_excluded, group) is False

    tags_bad_missing_or = {
        "owner": {"papa"},
        "mood": {"focus"},
        "context": {"morning"},
    }
    assert evaluate_group(tags_bad_missing_or, group) is False


def test_aggressive_fallback_removes_last_category_first():
    items = [Item("a", 1), Item("b", 2)]
    tags = [
        {"owner": {"papa"}},
        {"owner": {"papa"}, "mood": {"calm"}},
    ]

    group = TagQueryGroup(
        all_of=[
            TagFilter(category="owner", values=["papa"]),
            TagFilter(category="mood", values=["sleepy"]),
        ],
        any_of=[],
        none_of=[],
    )

    # strict match: none. aggressive fallback should drop mood and match both items.
    idx = apply_fallback(
        items=items,
        item_tags=tags,
        group=group,
        limit=10,
        fallback=SelectionFallback.aggressive,
        include_order=["owner", "mood"],
        tiebreak=lambda it: (-it.ts, it.id),
    )

    assert idx == [1, 0]  # ordered by tiebreak (ts desc)


def test_soft_fallback_scores_by_count_then_filter_order():
    items = [Item("A", 0), Item("B", 0), Item("C", 0)]
    tags = [
        {"mood": {"calm"}, "context": {"evening"}},           # 2 matches, but misses owner
        {"owner": {"papa"}, "mood": {"calm"}},               # 2 matches, includes owner (higher priority)
        {"owner": {"papa"}},                                   # 1 match
    ]

    group = TagQueryGroup(
        all_of=[
            TagFilter(category="owner", values=["papa"]),
            TagFilter(category="mood", values=["calm"]),
            TagFilter(category="context", values=["evening"]),
        ],
        any_of=[],
        none_of=[],
    )

    idx = apply_fallback(
        items=items,
        item_tags=tags,
        group=group,
        limit=3,
        fallback=SelectionFallback.soft,
        include_order=["owner", "mood", "context"],
        tiebreak=lambda it: (it.id,),
    )

    # B beats A because it matches the 1st filter (owner)
    assert idx[0] == 1
    # A beats C because it has 2 matches
    assert idx[1] == 0
    assert idx[2] == 2
