"""Shared types for the integration test metric extraction and comparison pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# (sorted_position, source_name_annotation).  The first element is the 0-based
# index in the canonically sorted list; the second is the object name carried
# for display in failure messages only -- never used for matching.
MetricKey = Tuple[int, str]

ExtractorFunction = Callable[[Dict[str, Any]], Dict[MetricKey, Dict]]

# Rounding precision for canonical sort keys.  Must be coarse enough that
# floating-point jitter never changes the sort order, but fine enough that
# genuinely different solids sort differently.
SORT_ROUND_DIGITS = 2


def solid_sort_key(metrics: Dict[str, Any]) -> Tuple[float, ...]:
    """Compute a canonical sort key for a solid from its metrics.

    The key is (volume, x_min, y_min, z_min, x_max, y_max, z_max) with values
    rounded for sort stability.

    Args:
        metrics: A solid's metrics dict containing at minimum "volume_mm3" and
            "bounding_box".

    Returns:
        A tuple of rounded floats suitable for use as a sort key.
    """
    r = SORT_ROUND_DIGITS
    vol = round(metrics.get("volume_mm3", 0.0), r)
    bb = metrics.get("bounding_box", {})
    return (
        vol,
        round(bb.get("x_min", 0.0), r),
        round(bb.get("y_min", 0.0), r),
        round(bb.get("z_min", 0.0), r),
        round(bb.get("x_max", 0.0), r),
        round(bb.get("y_max", 0.0), r),
        round(bb.get("z_max", 0.0), r),
    )


def _sortable_value(val: Any) -> Tuple[int, Union[float, str, int]]:
    """Convert a metric value to a sortable tuple for generic sort keys.

    Args:
        val: Any metric value.

    Returns:
        A tuple whose first element is a type-ordering int so that numeric
        values sort before strings, which sort before None.
    """
    if isinstance(val, bool):
        return (0, int(val))
    if isinstance(val, (int, float)):
        return (0, round(float(val), SORT_ROUND_DIGITS))
    if isinstance(val, str):
        return (1, val)
    return (2, 0)


def generic_sort_key(
    metrics: Dict[str, Any],
    priority_fields: Tuple[str, ...] = (),
) -> Tuple:
    """Build a canonical sort key from arbitrary metrics.

    Uses *priority_fields* first (in order), then all remaining scalar fields in
    alphabetical order.  Dict/list sub-values are skipped.

    Args:
        metrics: A metrics dictionary.
        priority_fields: Field names to use first in the key.

    Returns:
        A tuple suitable for use as a sort key.
    """
    parts: List[Tuple[int, Union[float, str, int]]] = []
    seen: set = set()
    for field in priority_fields:
        parts.append(_sortable_value(metrics.get(field)))
        seen.add(field)
    for field in sorted(metrics.keys()):
        if field in seen or field.startswith("_"):
            continue
        val = metrics[field]
        if isinstance(val, (dict, list)):
            continue
        parts.append(_sortable_value(val))
    return tuple(parts)


# Priority fields used when sorting entries in each non-solid section.
SECTION_SORT_PRIORITY: Dict[str, Tuple[str, ...]] = {
    "sketches": ("geometry_count", "constraint_count", "degrees_of_freedom"),
    "partdesign_bodies": ("feature_count",),
    "spreadsheets": ("cell_count",),
}


def make_simple_extractor(section: str) -> ExtractorFunction:
    """Create an extractor that reads a list-based report section and sorts by metrics.

    The report section is expected to be a list of dicts, each with "_source_name" and "metrics".
    Entries are sorted by a canonical key derived from their metrics, and returned as
    (position, source_name) -> metrics.

    Args:
        section: The top-level key in the JSON report to extract from (e.g. "sketches",
            "partdesign_bodies").

    Returns:
        An ExtractorFunction that maps each entry to a (sorted_position, source_name) -> metrics
        dict.
    """
    priority = SECTION_SORT_PRIORITY.get(section, ())

    def extract(report: Dict[str, Any]) -> Dict[MetricKey, Dict]:
        out: Dict[MetricKey, Dict] = {}
        entries = report.get(section, [])
        if not isinstance(entries, list):
            return out

        valid: List[Tuple[Tuple, str, Dict]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            metrics = entry.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            source_name = entry.get("_source_name") or entry.get("name", "?")
            key = generic_sort_key(metrics, priority)
            valid.append((key, source_name, metrics))

        valid.sort(key=lambda t: t[0])
        for i, (_, source_name, metrics) in enumerate(valid):
            out[(i, source_name)] = metrics
        return out

    return extract


@dataclass(frozen=True)
class CompareConfig:
    match_percentage: float  # e.g. 99.999
    absolute_tolerance: float  # absolute floor tolerance for near-zero values
    bbox_tolerance_mm: float  # absolute tolerance in mm for bounding box comparisons


@dataclass
class MetricDiff:
    key: MetricKey
    baseline: Optional[float]
    new: Optional[float]
    relative_error: Optional[float]
    ok: bool
    reason: str
