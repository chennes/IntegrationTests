"""Extractor for solid geometry metrics from the "solids" section of a report."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from metric_types import MetricKey, solid_sort_key


def extract_solid_metrics(report: Dict[str, Any]) -> Dict[MetricKey, Dict]:
    """Extract per-solid metrics from the "solids" section of a report.

    Reads the flat solids list, sorts it by a canonical geometric key
    (volume, bounding box), and returns a position-keyed map.  The object
    name is carried as an annotation for failure messages but is never used
    for matching.

    Args:
        report: A parsed JSON report dictionary produced by EvaluateFile.FCMacro.

    Returns:
        A dictionary mapping (sorted_position, source_name) tuples to their
        metrics dictionaries.
    """
    solids = report.get("solids", [])
    if not isinstance(solids, list):
        return {}

    valid: List[Tuple[Tuple[float, ...], str, Dict]] = []
    for entry in solids:
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics", {})
        if not isinstance(metrics, dict):
            continue
        source_name = entry.get("_source_name", "?")
        key = solid_sort_key(metrics)
        valid.append((key, source_name, metrics))

    valid.sort(key=lambda t: t[0])
    out: Dict[MetricKey, Dict] = {}
    for i, (_, source_name, metrics) in enumerate(valid):
        out[(i, source_name)] = metrics
    return out
