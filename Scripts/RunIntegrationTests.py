#!/usr/bin/env python3
"""
RunIntegrationTests.py

Runs a FreeCAD CLI metrics script against a folder of .FCStd files, parses the JSON output, and
compares per-object metrics to baselines with a fuzzy tolerance expressed as a required "match
percentage".

Baseline JSON files are expected to be named like the .FCStd file stem:
  model.FCStd -> <baseline_dir>/model.json

Usage:
  python RunIntegrationTests.py \
    --freecad /path/to/freecadcmd \
    --script /path/to/EvaluateFile.FCMacro \
    --fcstd-dir /path/to/fcstds \
    --baseline-dir /path/to/baselines \
    --match-percentage 99.999 \
    --absolute-tolerance-mm3 1e-9 \
    --filename model.FCStd

Exit codes:
  0 = all comparisons within tolerance
  2 = mismatches found
  3 = execution / I/O errors (missing files, FreeCAD failed, invalid JSON)
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from metric_types import MetricKey, CompareConfig, MetricDiff  # noqa: E402
from extractors import EXTRACTORS  # noqa: E402
from accepted_changes import (
    AcceptedChangeRule,
    load_accepted_changes,
    find_matching_rule,
)  # noqa: E402

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse command-line arguments for the test runner.

    Args:
        argv: Command-line arguments (typically sys.argv[1: ]).

    Returns:
        An argparse.Namespace with all configured options.
    """
    parser = argparse.ArgumentParser(
        description="Regression-compare FreeCAD object metrics vs baselines (JSON)."
    )
    parser.add_argument("--freecad", required=True, help="Path to FreeCADCmd/freecadcmd executable")
    parser.add_argument(
        "--script",
        required=True,
        help="Path to the FreeCAD JSON-emitting macro file (EvaluateFile.FCMacro)",
    )
    parser.add_argument("--fcstd-dir", required=True, help="Folder containing .FCStd files")
    parser.add_argument(
        "--baseline-dir",
        required=True,
        help="Folder containing baseline JSON files (stem-matched)",
    )
    parser.add_argument(
        "--match-percentage",
        type=float,
        default=99.999,
        help="Required match percentage. 99.999 => relative tolerance = 1 - 0.99999 = 1e-5",
    )
    parser.add_argument(
        "--absolute-tolerance-mm3",
        type=float,
        default=1e-9,
        help="Absolute tolerance in mm^3 used as a floor near zero (default: 1e-9)",
    )
    parser.add_argument(
        "--recursive", action="store_true", help="Recurse into subfolders of fcstd-dir"
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Per-file FreeCAD run timeout seconds (default: 300)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print per-file diffs (otherwise only summary + failures)",
    )
    parser.add_argument(
        "--filename", required=False, help="Individual file to test (FCStd name only, not path)"
    )
    parser.add_argument(
        "--exceptions-dir",
        required=False,
        default=None,
        help="Folder containing accepted-change exception JSON files (optional)",
    )
    parser.add_argument(
        "--known-failures-dir",
        required=False,
        default=None,
        help="Folder containing known-failure rule JSON files (optional)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Ignore all accepted-change exceptions and known failures; report every mismatch",
    )
    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Tolerance helpers
# ---------------------------------------------------------------------------


def required_relative_tolerance(match_percentage: float) -> float:
    """Convert a match percentage to a relative tolerance value.

    For example, 99.999% match yields a relative tolerance of 1e-5.

    Args:
        match_percentage: The required match percentage, in the range (0, 100].

    Returns:
        The relative tolerance as a float (1.0 - match_percentage / 100.0).

    Raises:
        ValueError: If match_percentage is not in (0, 100].
    """
    if not (0.0 < match_percentage <= 100.0):
        raise ValueError("match_percentage must be in (0, 100].")
    return 1.0 - (match_percentage / 100.0)


# ---------------------------------------------------------------------------
# FreeCAD invocation
# ---------------------------------------------------------------------------


def run_freecad_script(
    freecad_exe: Path, script_path: Path, fcstd_path: Path, timeout_s: float
) -> Dict[str, Any]:
    """Run the EvaluateFile macro on a single FCStd file and return the parsed JSON report.

    Launches FreeCADCmd as a subprocess with an isolated configuration directory to ensure pristine
    settings and avoid overwriting the user's real config. Uses both FREECAD_USER_HOME (0.19+) and
    --user-cfg/--system-cfg (all versions) for cross-version compatibility.

    Args:
        freecad_exe: Path to the FreeCADCmd executable.
        script_path: Path to the EvaluateFile.FCMacro script.
        fcstd_path: Path to the .FCStd file to evaluate.
        timeout_s: Maximum time in seconds to wait for the subprocess.

    Returns:
        The parsed JSON report as a dictionary.

    Raises:
        RuntimeError: Raised if FreeCADCmd exits with a non-zero return code, produces no output, or
        produces invalid JSON.
        subprocess.TimeoutExpired: If the subprocess exceeds timeout_s.
    """
    with tempfile.TemporaryDirectory() as temp_dir:
        output_file = os.path.join(temp_dir, "output.json")
        config_dir = os.path.join(temp_dir, "config")
        os.makedirs(config_dir)

        cmd = [str(freecad_exe), str(script_path), str(fcstd_path), "--out", output_file]

        env = os.environ.copy()
        env["FREECAD_USER_HOME"] = config_dir

        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            env=env,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"FreeCAD run failed (rc={proc.returncode}) for {fcstd_path}\n"
                f"STDERR:\n{proc.stderr.strip()}\n\n"
                f"STDOUT (first 2000 chars):\n{proc.stdout[:2000].strip()}"
            )

        with open(output_file, "r", encoding="utf-8") as f:
            out = f.read()

        if not out:
            raise RuntimeError(f"No data in JSON output file generated from {fcstd_path}")

    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Invalid JSON from FreeCAD for {fcstd_path}: {e}\n"
            f"STDOUT (first 2000 chars):\n{out[:2000]}"
        )


def load_json(path: Path) -> Dict[str, Any]:
    """Load and parse a JSON file.

    Args:
        path: Path to the JSON file.

    Returns:
        The parsed JSON content as a dictionary.
    """
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Comparison engine
# ---------------------------------------------------------------------------


def compare_maps(
    baseline: Dict[MetricKey, Dict], new: Dict[MetricKey, Dict], config: CompareConfig
) -> List[MetricDiff]:
    """Compare two metric maps and return a list of diffs for all keys.

    Keys present in one map but not the other are reported as missing. Keys present in both are
    compared recursively via compare_individual_metrics.

    Args:
        baseline: Metric map from the baseline report.
        new: Metric map from the newly generated report.
        config: Tolerance configuration for fuzzy float comparisons.

    Returns:
        A list of MetricDiff objects, one per comparison (including passing ones).
    """
    diffs: List[MetricDiff] = []

    all_keys = set(baseline.keys()) | set(new.keys())
    for key in sorted(all_keys, key=lambda k: (k[0], k[1])):
        baseline_metrics = baseline.get(key)
        new_metrics = new.get(key)

        if baseline_metrics is None:
            diffs.append(
                MetricDiff(
                    key=key,
                    baseline=None,
                    new=new_metrics,
                    relative_error=None,
                    ok=False,
                    reason="missing_in_baseline",
                )
            )
            continue
        if new_metrics is None:
            diffs.append(
                MetricDiff(
                    key=key,
                    baseline=None,
                    new=None,
                    relative_error=None,
                    ok=False,
                    reason="missing_in_new",
                )
            )
            continue

        diffs.extend(
            compare_individual_metrics(config, key, "metric", baseline_metrics, new_metrics)
        )

    return diffs


def compare_individual_metrics(
    config: CompareConfig, key: MetricKey, metric: str, baseline: Any, new: Any
) -> List[MetricDiff]:
    """Recursively compare a baseline metric value against a new value.

    Handles floats (fuzzy comparison using config tolerances), ints, bools, and strings (exact
    comparison), and dicts (recursive descent into sub-metrics).

    Args:
        config: Tolerance configuration for fuzzy float comparisons.
        key: The (object_name, index) key this metric belongs to.
        metric: A dot-path-style name for the metric being compared (e.g.
            "metric_bounding_box_x_min"), used in diff reason strings.
        baseline: The baseline metric value.
        new: The newly computed metric value.

    Returns:
        A list of MetricDiff objects for this metric and any sub-metrics.

    Raises:
        ValueError: If the metric value is not a supported type (float, int, bool, str, or dict).
    """
    if baseline is None and new is None:
        return [
            MetricDiff(key=key, baseline=None, new=None, relative_error=0, ok=True, reason="ok")
        ]
    if baseline is None or new is None:
        ok = baseline == new
        return [
            MetricDiff(
                key=key,
                baseline=baseline,
                new=new,
                relative_error=0,
                ok=ok,
                reason="ok" if ok else f"{metric}_mismatch",
            )
        ]
    # A baseline value of -1 for int metrics is a sentinel meaning "not reported by this FreeCAD
    # version" (e.g. Sketcher DoF was unavailable before 0.21, Spreadsheet cell_count before 1.0).
    # Skip the comparison rather than flag a false mismatch.
    if isinstance(baseline, int) and baseline == -1 and isinstance(new, int):
        return [
            MetricDiff(key=key, baseline=baseline, new=new, relative_error=0, ok=True, reason="ok")
        ]
    if not isinstance(baseline, type(new)):
        return [
            MetricDiff(
                key=key,
                baseline=baseline,
                new=new,
                relative_error=0,
                ok=False,
                reason=f"value_type_mismatch_for_{metric}",
            )
        ]
    if isinstance(baseline, int) or isinstance(baseline, bool) or isinstance(baseline, str):
        ok = baseline == new
        return [
            MetricDiff(
                key=key,
                baseline=baseline,
                new=new,
                relative_error=0,
                ok=ok,
                reason="ok" if ok else f"{metric}_mismatch",
            )
        ]
    elif isinstance(baseline, float):
        # Fuzzy compare: pass if |new-baseline| <= max(absolute_tolerance, relative_tolerance*max(|baseline|,|new|))
        relative_tolerance = required_relative_tolerance(config.match_percentage)
        denominator = max(abs(baseline), abs(new))
        tolerance = max(config.absolute_tolerance_mm3, relative_tolerance * denominator)
        error = abs(new - baseline)

        ok = error <= tolerance
        relative_error = (
            (error / denominator) if denominator > 0 else (0.0 if error == 0 else math.inf)
        )

        return [
            MetricDiff(
                key=key,
                baseline=baseline,
                new=new,
                relative_error=relative_error,
                ok=ok,
                reason="ok" if ok else f"{metric}_mismatch",
            )
        ]
    elif isinstance(baseline, dict):
        # Recursively descend into this dictionary
        results = []
        sub_metrics = baseline.keys() | new.keys()
        for sub_metric in sub_metrics:
            if sub_metric not in new:
                results.append(
                    MetricDiff(
                        key=key,
                        baseline=None,
                        new=new,
                        relative_error=None,
                        ok=False,
                        reason=f"{metric}_{sub_metric}_missing_in_new",
                    )
                )
            elif sub_metric not in baseline:
                print("  WARNING: baseline missing metric:", f"{metric}_{sub_metric}")
            else:
                results.extend(
                    compare_individual_metrics(
                        config,
                        key,
                        f"{metric}_{sub_metric}",
                        baseline[sub_metric],
                        new[sub_metric],
                    )
                )
        return results
    raise ValueError(f"Unrecognized data type for {metric}")


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------


def find_fcstd_files(root: Path, recursive: bool) -> List[Path]:
    """Find all .FCStd files in a directory, sorted alphabetically.

    Args:
        root: The directory to search.
        recursive: If True, search subdirectories recursively.

    Returns:
        A sorted list of Path objects for each FreeCAD file that is found.
    """
    if recursive:
        return sorted([path for path in root.rglob("*.FCStd") if path.is_file()])
    return sorted([path for path in root.glob("*.FCStd") if path.is_file()])


# ---------------------------------------------------------------------------
# Diff reporting
# ---------------------------------------------------------------------------


def print_diff(diff: MetricDiff, config: CompareConfig) -> None:
    """Print a single metric diff to stdout in a human-readable format.

    Formats the output differently depending on the type of mismatch: missing objects, failed
    recomputation, floating-point deviations, or exact-match failures.

    Args:
        diff: The MetricDiff to print.
        config: The comparison config, used to display the required match percentage.
    """
    if diff.reason == "missing_in_baseline":
        print(f"  - Feature exists in newly-recomputed file, but not in baseline: {diff.key[0]}")
    elif diff.reason == "missing_in_new":
        print(f"  - Feature exists in baseline, but not in newly-recomputed file: {diff.key[0]}")
    elif isinstance(diff.new, dict) and not diff.new.get("is_valid", True):
        print(f"  - Recomputation of {diff.key[0]} failed")
    elif (
        isinstance(diff.baseline, float)
        and isinstance(diff.new, float)
        and diff.relative_error != 0.0
    ):
        relative_error_percent = (
            (diff.relative_error * 100.0)
            if (diff.relative_error is not None and math.isfinite(diff.relative_error))
            else None
        )
        relative_error_string = (
            f"{relative_error_percent:.9f}%" if relative_error_percent is not None else "inf"
        )
        print(
            f"  - {diff.reason} {diff.key}:"
            f" baseline={diff.baseline:.12g} new={diff.new:.12g}"
            f" relative_error={relative_error_string}"
            f" (required match >= {config.match_percentage}%)"
        )
    else:
        print(f"  - {diff.reason} {diff.key}: baseline={diff.baseline} new={diff.new}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(argv: List[str]) -> int:
    """Run the integration test suite.

    For each .FCStd file in the test directory, runs EvaluateFile.FCMacro via FreeCADCmd, extracts
    metrics from the output, and compares them against stored baselines using fuzzy tolerances.
    Prints per-file results and a summary.

    Args:
        argv: Command-line arguments (typically sys.argv[1: ]).

    Returns:
        0 if all tests pass, 2 if any mismatches are found, or 3 if errors
        occurred (e.g. FreeCAD crashes, missing files).
    """
    args = parse_args(argv)

    freecad_exe = Path(args.freecad)
    script_path = Path(args.script)
    fcstd_dir = Path(args.fcstd_dir)
    baseline_dir = Path(args.baseline_dir)
    exceptions_dir = Path(args.exceptions_dir) if args.exceptions_dir else None
    known_failures_dir = Path(args.known_failures_dir) if args.known_failures_dir else None
    use_exceptions = exceptions_dir is not None and not args.strict
    use_known_failures = known_failures_dir is not None and not args.strict

    single_test_to_run = None
    if args.filename:
        single_test_to_run = fcstd_dir / args.filename
        if not single_test_to_run.exists():
            print(f"ERROR: File does not exist: {single_test_to_run}", file=sys.stderr)
            return 3

    required_paths = [freecad_exe, script_path, fcstd_dir, baseline_dir]
    if exceptions_dir is not None:
        required_paths.append(exceptions_dir)
    if known_failures_dir is not None:
        required_paths.append(known_failures_dir)
    for path in required_paths:
        if not path.exists():
            print(f"ERROR: Path does not exist: {path}", file=sys.stderr)
            return 3

    config = CompareConfig(
        match_percentage=float(args.match_percentage),
        absolute_tolerance_mm3=float(args.absolute_tolerance_mm3),
    )

    fcstd_files = find_fcstd_files(fcstd_dir, args.recursive)
    if not fcstd_files:
        print(f"ERROR: No .FCStd files found in: {fcstd_dir}", file=sys.stderr)
        return 3

    total_files = 0
    ok_files = 0
    mismatch_files = 0
    known_failure_files = 0
    error_files = 0
    total_accepted = 0
    total_known_failures = 0

    date_string = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    for fcstd_path in fcstd_files:
        if single_test_to_run and fcstd_path != single_test_to_run:
            continue
        total_files += 1
        stem = fcstd_path.stem
        baseline_path = baseline_dir / f"{stem}.json"

        if not baseline_path.exists():
            print(f"[FAIL] {fcstd_path.name}: baseline missing: {baseline_path}", file=sys.stderr)
            mismatch_files += 1
            continue

        try:
            new_report = run_freecad_script(
                freecad_exe=freecad_exe,
                script_path=script_path,
                fcstd_path=fcstd_path,
                timeout_s=float(args.timeout),
            )
            base_report = load_json(baseline_path)

            # Run all extractors and collect diffs per section
            section_diffs: Dict[str, List[MetricDiff]] = {}
            for section_name, extract_function in EXTRACTORS:
                new_map = extract_function(new_report)
                base_map = extract_function(base_report)
                diffs = compare_maps(base_map, new_map, config)
                section_diffs[section_name] = diffs

            # Collect all failing diffs with their section context
            bad_with_section: List[tuple] = []
            for section_name, diffs in section_diffs.items():
                for diff in diffs:
                    if not diff.ok:
                        bad_with_section.append((section_name, diff))

            # Partition into accepted, known failures, and truly-bad
            accepted: List[tuple] = []
            known: List[tuple] = []
            truly_bad: List[tuple] = []
            remaining = bad_with_section

            # First pass: accepted exceptions
            if use_exceptions and remaining:
                rules = load_accepted_changes(exceptions_dir, stem)
                next_remaining = []
                for section_name, diff in remaining:
                    rule = find_matching_rule(diff, section_name, rules)
                    if rule is not None:
                        accepted.append((section_name, diff, rule))
                    else:
                        next_remaining.append((section_name, diff))
                remaining = next_remaining

            # Second pass: known failures
            if use_known_failures and remaining:
                kf_rules = load_accepted_changes(known_failures_dir, stem)
                next_remaining = []
                for section_name, diff in remaining:
                    rule = find_matching_rule(diff, section_name, kf_rules)
                    if rule is not None:
                        known.append((section_name, diff, rule))
                    else:
                        next_remaining.append((section_name, diff))
                remaining = next_remaining

            truly_bad = remaining

            total_accepted += len(accepted)
            total_known_failures += len(known)

            if truly_bad:
                mismatch_files += 1
                print(f"[FAIL] {fcstd_path.name}: {len(truly_bad)} failure(s)")
                for _, diff in truly_bad:
                    print_diff(diff, config)
                if known:
                    print(f"  ({len(known)} additional difference(s) are known failures)")
                if accepted:
                    print(
                        f"  ({len(accepted)} additional difference(s) accepted by exception rules)"
                    )
                if args.verbose:
                    for section_name, diff, rule in known:
                        print(
                            f"    [known] {diff.reason} {diff.key}"
                            f" -- {rule.description} ({rule.source})"
                        )
                    for section_name, diff, rule in accepted:
                        print(
                            f"    [accepted] {diff.reason} {diff.key}"
                            f" -- {rule.description} ({rule.source})"
                        )
                    for section_name, _ in EXTRACTORS:
                        diffs = section_diffs[section_name]
                        bad_count = sum(1 for diff in diffs if not diff.ok)
                        print(
                            f"  {section_name} compared: {len(diffs)}"
                            f" (ok={len(diffs) - bad_count}"
                            f" bad={bad_count})"
                        )
                new_report_file = Path.cwd() / date_string / f"{stem}_new.json"
                os.makedirs(new_report_file.parent, exist_ok=True)
                with open(new_report_file, "w", encoding="utf-8") as f:
                    json.dump(new_report, f, indent=2)
            elif known:
                known_failure_files += 1
                print(f"[XFAIL] {fcstd_path.name}: {len(known)} known failure(s)")
                if args.verbose:
                    for section_name, diff, rule in known:
                        print(
                            f"    [known] {diff.reason} {diff.key}"
                            f" -- {rule.description} ({rule.source})"
                        )
                if accepted:
                    print(
                        f"  ({len(accepted)} additional difference(s) accepted by exception rules)"
                    )
            elif accepted:
                ok_files += 1
                print(f"[OK]   {fcstd_path.name}: {len(accepted)} accepted change(s)")
                if args.verbose:
                    for section_name, diff, rule in accepted:
                        print(
                            f"    [accepted] {diff.reason} {diff.key}"
                            f" -- {rule.description} ({rule.source})"
                        )
                    parts = ["         "]
                    for section_name, _ in EXTRACTORS:
                        diffs = section_diffs[section_name]
                        parts.append(f"{section_name}={len(diffs)}")
                    print(" ".join(parts))
            else:
                ok_files += 1
                if args.verbose:
                    parts = [f"[OK]   {fcstd_path.name}:"]
                    for section_name, _ in EXTRACTORS:
                        diffs = section_diffs[section_name]
                        parts.append(f"{section_name}={len(diffs)}")
                    print(" ".join(parts))

        except subprocess.TimeoutExpired:
            error_files += 1
            print(f"[ERROR] {fcstd_path.name}: timed out after {args.timeout}s", file=sys.stderr)
        except Exception as e:
            error_files += 1
            print(f"[ERROR] {fcstd_path.name}: {e}", file=sys.stderr)
            traceback.print_exception(type(e), e, e.__traceback__, file=sys.stderr)

    print("\n" + 35 * "=" + " Summary " + 35 * "=")
    print(f"Files checked: {total_files}")
    print(f"OK:            {ok_files}")
    if known_failure_files > 0:
        print(f"Known fails:   {known_failure_files}")
    print(f"Mismatched:    {mismatch_files}")
    print(f"Errors:        {error_files}")
    if total_accepted > 0:
        print(f"Accepted:      {total_accepted} difference(s)")
    if total_known_failures > 0:
        print(f"Known:         {total_known_failures} difference(s)")
    print(
        f"Match pct:     {config.match_percentage}"
        f" (relative_tolerance={required_relative_tolerance(config.match_percentage):.12g})"
    )
    print(f"Abs tol mm^3:  {config.absolute_tolerance_mm3:.12g}")
    if use_exceptions:
        print(f"Exceptions:    {exceptions_dir}")
    if use_known_failures:
        print(f"Known fails:   {known_failures_dir}")
    if args.strict:
        print("Strict mode:   all exceptions and known failures disabled")
    print(79 * "=")

    if mismatch_files or error_files:
        print("Integration tests failed")
    elif known_failure_files > 0:
        print("Integration tests passed (with known failures)")
    else:
        print("Integration tests passed")

    # Machine-readable summary for CI badge generation
    print(
        f"BADGE_JSON:"
        f'{{"ok":{ok_files},"xfail":{known_failure_files},'
        f'"fail":{mismatch_files},"error":{error_files}}}'
    )

    if error_files > 0:
        return 3
    if mismatch_files > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
