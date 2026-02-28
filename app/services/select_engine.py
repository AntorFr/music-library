"""Selection engine used by Home Assistant-facing endpoints.

This module is intentionally side-effect free and unit-test friendly.
It implements:
- Boolean tag query evaluation (all_of/any_of/none_of)
- Fallback modes: none | aggressive | soft
- Query-string parsing helpers that preserve parameter order

Notes:
- OR within a category is represented by a single TagFilter with multiple values.
- AND across categories is represented by multiple TagFilters (different categories).
- Exclusions (none_of) are always strict and never relaxed by fallback.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TypeVar
import unicodedata

from app.schemas.media import SelectionFallback, TagFilter, TagQueryGroup

T = TypeVar("T")


def normalize_select_token(value: str) -> str:
    text = (value or "").strip().casefold()
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in value.split(",") if p.strip()]


@dataclass(frozen=True)
class ParsedTagFilters:
    include_values: dict[str, set[str]]
    exclude_values: dict[str, set[str]]
    include_order: list[str]


def parse_tag_filters_from_qsl(
    pairs: Sequence[tuple[str, str]],
    *,
    reserved_keys: set[str] | None = None,
) -> ParsedTagFilters:
    """Parse tag include/exclude filters from ordered query-string pairs.

    Supported keys:
    - <category>=a,b          → include values for that category
    - tag_<slug>=a,b          → include values for dynamic category
    - not_<category>=a,b      → exclude values for that category
    - not_tag_<slug>=a,b      → exclude values for dynamic category

    The order of first appearance of included categories is preserved.
    """

    reserved_keys = reserved_keys or set()

    include_values: dict[str, set[str]] = {}
    exclude_values: dict[str, set[str]] = {}
    include_order: list[str] = []

    def ensure_order(cat: str) -> None:
        if cat not in include_values and cat not in include_order:
            include_order.append(cat)

    for key, raw_value in pairs:
        if not key or key in reserved_keys:
            continue
        if raw_value is None or raw_value == "":
            continue

        is_exclusion = False
        category = key

        if key.startswith("not_tag_"):
            is_exclusion = True
            category = key[len("not_tag_") :]
        elif key.startswith("not_"):
            is_exclusion = True
            category = key[len("not_") :]
        elif key.startswith("tag_"):
            category = key[len("tag_") :]

        category = (category or "").strip().casefold()
        if not category:
            continue

        values = [normalize_select_token(v) for v in split_csv(raw_value)]
        values = [v for v in values if v]
        if not values:
            continue

        if is_exclusion:
            exclude_values.setdefault(category, set()).update(values)
        else:
            ensure_order(category)
            include_values.setdefault(category, set()).update(values)

    return ParsedTagFilters(include_values=include_values, exclude_values=exclude_values, include_order=include_order)


def build_simple_group(
    include_values: Mapping[str, set[str]],
    exclude_values: Mapping[str, set[str]],
    include_order: Sequence[str],
) -> TagQueryGroup:
    """Build a TagQueryGroup equivalent to current GET /select behavior."""

    all_of: list[TagFilter] = []
    for cat in include_order:
        vals = sorted(include_values.get(cat, set()))
        if vals:
            all_of.append(TagFilter(category=cat, values=vals))

    none_of: list[TagFilter] = []
    for cat, vals_set in exclude_values.items():
        vals = sorted(vals_set)
        if vals:
            none_of.append(TagFilter(category=cat, values=vals))

    return TagQueryGroup(all_of=all_of, none_of=none_of, any_of=[])


def _matches_filter(item_tags: Mapping[str, set[str]], flt: TagFilter) -> bool:
    values = item_tags.get(flt.category)
    if not values:
        return False
    wanted = set(flt.values)
    return bool(values.intersection(wanted))


def evaluate_group(item_tags: Mapping[str, set[str]], group: TagQueryGroup) -> bool:
    """Evaluate a boolean TagQueryGroup against an item's tags."""

    # Exclusion (strict)
    for flt in group.none_of:
        if _matches_filter(item_tags, flt):
            return False

    # Inclusion (strict)
    for flt in group.all_of:
        if not _matches_filter(item_tags, flt):
            return False

    # OR groups
    if group.any_of:
        return any(evaluate_group(item_tags, sub) for sub in group.any_of)

    return True


def apply_fallback(
    *,
    items: Sequence[T],
    item_tags: Sequence[Mapping[str, set[str]]],
    group: TagQueryGroup,
    limit: int,
    fallback: SelectionFallback,
    include_order: Sequence[str] | None = None,
    passes_strict: Callable[[int], bool] | None = None,
    tiebreak: Callable[[T], tuple] | None = None,
) -> list[int]:
    """Return selected indices in `items` after applying fallback.

    `passes_strict(i)` should apply strict, non-tag constraints that are never relaxed
    (e.g. media_type/provider/exclude_ids). When omitted, all items are considered.

    `include_order` is used for aggressive/soft fallback; it should represent the
    order filters were provided by the client.

    Returns a list of indices (not the items themselves) to keep this pure.
    """

    if passes_strict is None:
        passes_strict = lambda _i: True  # noqa: E731

    strict_indices = [i for i in range(len(items)) if passes_strict(i)]

    def strict_match(i: int, g: TagQueryGroup) -> bool:
        return passes_strict(i) and evaluate_group(item_tags[i], g)

    matches = [i for i in strict_indices if evaluate_group(item_tags[i], group)]
    if matches:
        return matches[:limit]

    if fallback == SelectionFallback.none:
        return []

    include_order = list(include_order or [f.category for f in group.all_of])

    if fallback == SelectionFallback.aggressive:
        # Remove include categories in reverse order until we get a match.
        current_all_of = list(group.all_of)
        # Map category -> TagFilter index for quick removal.
        def rebuild_group(keep_categories: set[str]) -> TagQueryGroup:
            new_all = [f for f in current_all_of if f.category in keep_categories]
            return TagQueryGroup(all_of=new_all, any_of=group.any_of, none_of=group.none_of)

        keep = set(include_order)
        # Try progressively removing the last declared category.
        for k in range(len(include_order), -1, -1):
            keep = set(include_order[:k])
            g2 = rebuild_group(keep)
            matches2 = [i for i in strict_indices if evaluate_group(item_tags[i], g2)]
            if matches2:
                if tiebreak is not None:
                    matches2.sort(key=lambda i: tiebreak(items[i]))
                return matches2[:limit]
        return []

    if fallback == SelectionFallback.force:
        # Relax filters progressively until we reach `limit` results.
        # Prioritize items matching the most criteria (like soft).
        current_all_of = list(group.all_of)

        def rebuild_group_force(keep_categories: set[str]) -> TagQueryGroup:
            new_all = [f for f in current_all_of if f.category in keep_categories]
            return TagQueryGroup(all_of=new_all, any_of=group.any_of, none_of=group.none_of)

        def passes_exclusion_force(i: int) -> bool:
            if not passes_strict(i):
                return False
            for flt in group.none_of:
                if _matches_filter(item_tags[i], flt):
                    return False
            return True

        ordered_filters_force = []
        by_cat_force = {f.category: f for f in group.all_of}
        for cat in include_order:
            flt = by_cat_force.get(cat)
            if flt:
                ordered_filters_force.append(flt)

        if tiebreak is None:
            tiebreak = lambda _item: tuple()  # noqa: E731

        def sort_key_force(i: int) -> tuple:
            matches_vec = [_matches_filter(item_tags[i], flt) for flt in ordered_filters_force]
            count = sum(1 for m in matches_vec if m)
            vec_key = tuple(0 if m else 1 for m in matches_vec)
            return (-count, *vec_key, *tiebreak(items[i]))

        collected: list[int] = []
        seen: set[int] = set()

        # Try progressively removing filters from the end.
        for k in range(len(include_order), -1, -1):
            keep = set(include_order[:k])
            g2 = rebuild_group_force(keep)
            batch = [
                i for i in strict_indices
                if i not in seen and passes_exclusion_force(i) and evaluate_group(item_tags[i], g2)
            ]
            batch.sort(key=sort_key_force)
            for i in batch:
                if i not in seen:
                    seen.add(i)
                    collected.append(i)
                    if len(collected) >= limit:
                        return collected

        return collected

    # soft fallback
    if not group.all_of:
        return []

    ordered_filters: list[TagFilter] = []
    by_cat = {f.category: f for f in group.all_of}
    for cat in include_order:
        flt = by_cat.get(cat)
        if flt:
            ordered_filters.append(flt)

    def passes_exclusion(i: int) -> bool:
        if not passes_strict(i):
            return False
        # exclusion clauses only
        for flt in group.none_of:
            if _matches_filter(item_tags[i], flt):
                return False
        return True

    # candidates matching at least one desired tag
    candidates: list[int] = []
    for i in strict_indices:
        if not passes_exclusion(i):
            continue
        if any(_matches_filter(item_tags[i], flt) for flt in ordered_filters):
            candidates.append(i)

    if not candidates:
        return []

    if tiebreak is None:
        tiebreak = lambda _item: tuple()  # noqa: E731

    def sort_key(i: int) -> tuple:
        matches_vec = [
            _matches_filter(item_tags[i], flt)
            for flt in ordered_filters
        ]
        count = sum(1 for m in matches_vec if m)
        # Prefer higher count, then earlier filters matching, then tiebreak.
        vec_key = tuple(0 if m else 1 for m in matches_vec)
        return (-count, *vec_key, *tiebreak(items[i]))

    candidates.sort(key=sort_key)
    return candidates[:limit]
