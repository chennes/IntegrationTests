"""Load and match "accepted change" exception rules for the integration test suite.

Exception rules allow known, intentional differences between FreeCAD versions to be downgraded
from failures to warnings. Rules are stored as JSON files in an exceptions directory:

  Data/Exceptions/_global.json   -- rules that apply to all test files
  Data/Exceptions/<stem>.json    -- rules that apply only to a specific FCStd file

Each JSON file contains a top-level object with a "rules" array. See AcceptedChangeRule for the
fields in each rule.
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from metric_types import MetricDiff


@dataclass(frozen=True)
class AcceptedChangeRule:
    """A rule describing an acceptable metric difference.

    Attributes:
        section: fnmatch pattern matched against the extractor section name (e.g.
            "part_features", or "*" for all sections).
        object_pattern: fnmatch pattern matched against the object name (diff.key[0]),
            e.g. "Wall*".
        metric_pattern: fnmatch pattern matched against the diff's reason string (e.g.
            "*shape_type*"). Defaults to "*" (match any reason).
        accepted_values: If provided, the diff's new value must appear in this list for the rule
            to match. If None, any new value is accepted.
        description: Human-readable explanation of why this change is acceptable.
        added: ISO date string recording when the rule was added (e.g. "2026-03-13").
        source: The file this rule was loaded from (set automatically during loading).
    """

    section: str
    object_pattern: str
    description: str
    metric_pattern: str = "*"
    accepted_values: Optional[List[Any]] = None
    added: str = ""
    source: str = ""

    def matches(self, section: str, diff: MetricDiff) -> bool:
        """Check whether this rule applies to a given diff in a given section.

        Args:
            section: The extractor section name (e.g. "part_features").
            diff: The failing MetricDiff to check.

        Returns:
            True if every field in the rule matches the diff.
        """
        if not fnmatch.fnmatch(section, self.section):
            return False
        if not fnmatch.fnmatch(diff.key[0], self.object_pattern):
            return False
        if self.metric_pattern != "*":
            if not fnmatch.fnmatch(diff.reason, self.metric_pattern):
                return False
        if self.accepted_values is not None:
            if diff.new not in self.accepted_values:
                return False
        return True


def load_accepted_changes(exceptions_dir: Path, file_stem: str) -> List[AcceptedChangeRule]:
    """Load accepted change rules from the global and per-file exception files.

    Global rules (from _global.json) are loaded first, then per-file rules (from <file_stem>.json).
    This means per-file rules are checked after global rules during matching.

    Args:
        exceptions_dir: Path to the directory containing exception JSON files.
        file_stem: The stem of the FCStd file being tested (e.g. "BIMExample").

    Returns:
        A combined list of rules, global first, then per-file.
    """
    rules: List[AcceptedChangeRule] = []

    global_path = exceptions_dir / "_global.json"
    if global_path.is_file():
        rules.extend(_load_rules_from_file(global_path))

    file_path = exceptions_dir / f"{file_stem}.json"
    if file_path.is_file():
        rules.extend(_load_rules_from_file(file_path))

    return rules


def _load_rules_from_file(path: Path) -> List[AcceptedChangeRule]:
    """Parse a single exception JSON file into a list of rules.

    Args:
        path: Path to the JSON exception file.

    Returns:
        A list of AcceptedChangeRule objects parsed from the file.
    """
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return []
    raw_rules = data.get("rules", [])
    if not isinstance(raw_rules, list):
        return []

    rules: List[AcceptedChangeRule] = []
    for entry in raw_rules:
        if not isinstance(entry, dict):
            continue
        rules.append(
            AcceptedChangeRule(
                section=entry["section"],
                object_pattern=entry["object_pattern"],
                description=entry.get("description", ""),
                metric_pattern=entry.get("metric_pattern", "*"),
                accepted_values=entry.get("accepted_values"),
                added=entry.get("added", ""),
                source=str(path.name),
            )
        )
    return rules


def find_matching_rule(
    diff: MetricDiff, section: str, rules: List[AcceptedChangeRule]
) -> Optional[AcceptedChangeRule]:
    """Find the first exception rule that matches a failing diff.

    Args:
        diff: The failing MetricDiff to check.
        section: The extractor section name this diff belongs to.
        rules: The list of loaded exception rules.

    Returns:
        The first matching AcceptedChangeRule, or None if no rule matches.
    """
    for rule in rules:
        if rule.matches(section, diff):
            return rule
    return None
