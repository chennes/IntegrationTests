"""Extractor for solid geometry metrics from the "objects" section of a report."""

from __future__ import annotations

from typing import Any, Dict

from metric_types import MetricKey


def extract_solid_metrics(report: Dict[str, Any]) -> Dict[MetricKey, Dict]:
    """Extract per-solid metrics from the "objects" section of a report.

    Walks the report's "objects" dictionary and flattens each solid entry into a (object_name,
    index) -> metrics mapping suitable for comparison.

    Args:
        report: A parsed JSON report dictionary produced by EvaluateFile.FCMacro.

    Returns:
        A dictionary mapping (object_name, solid_index) tuples to their metrics
        dictionaries.
    """
    out: Dict[MetricKey, Dict] = {}
    objects = report.get("objects", {})
    if not isinstance(objects, dict):
        return out
    for obj_name, obj_entry in objects.items():
        if not isinstance(obj_entry, dict):
            continue
        solids = obj_entry.get("solids", [])
        if not isinstance(solids, list):
            continue
        for solid_entry in solids:
            if not isinstance(solid_entry, dict):
                continue
            object_name = solid_entry.get("object_name") or obj_name
            index = solid_entry.get("index")
            metrics = solid_entry.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            if isinstance(object_name, str) and isinstance(index, int):
                out[(object_name, index)] = metrics
    return out
