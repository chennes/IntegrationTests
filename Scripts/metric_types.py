"""Shared types for the integration test metric extraction and comparison pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

# Object name used for matching between baseline and new reports.
MetricKey = str

ExtractorFunction = Callable[[Dict[str, Any]], Dict[MetricKey, Dict]]


def make_simple_extractor(section: str) -> ExtractorFunction:
    """Create an extractor that reads a list-based report section keyed by object name.

    The report section is expected to be a list of dicts, each with "_source_name" and "metrics".

    Args:
        section: The top-level key in the JSON report to extract from (e.g. "sketches",
            "partdesign_bodies").

    Returns:
        An ExtractorFunction that maps each entry's source_name to its metrics dict.
    """

    def extract(report: Dict[str, Any]) -> Dict[MetricKey, Dict]:
        out: Dict[MetricKey, Dict] = {}
        entries = report.get(section, [])
        if not isinstance(entries, list):
            return out

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            metrics = entry.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            out[entry.get("_source_name", "?")] = metrics
        return out

    return extract


@dataclass(frozen=True)
class CompareConfig:
    match_percentage: float  # e.g. 99.99
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
