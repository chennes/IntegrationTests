"""Shared types for the integration test metric extraction and comparison pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Tuple, Any, Optional

MetricKey = Tuple[str, int]  # (object_name, index)
ExtractorFunction = Callable[[Dict[str, Any]], Dict[MetricKey, Dict]]


def make_simple_extractor(section: str) -> ExtractorFunction:
    """Create an extractor that pulls (name, 0) -> metrics from a named report section.

    Most report sections share identical structure: a dict of named entries, each containing a
    "metrics" sub-dict. This factory produces an extractor function for any such section, avoiding
    per-section boilerplate.

    Args:
        section: The top-level key in the JSON report to extract from (e.g. "sketches",
            "partdesign_bodies").

    Returns:
        An ExtractorFunction that maps each entry in the section to a (name, 0) -> metrics dict.
    """

    def extract(report: Dict[str, Any]) -> Dict[MetricKey, Dict]:
        out: Dict[MetricKey, Dict] = {}
        entries = report.get(section, {})
        if not isinstance(entries, dict):
            return out
        for name, entry in entries.items():
            if not isinstance(entry, dict):
                continue
            metrics = entry.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            out[(name, 0)] = metrics
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
