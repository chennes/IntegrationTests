#!/usr/bin/env python3
"""Test library files across multiple FreeCAD versions and record results.

For each pre-0.21 test-suitable file in library_analysis.json:
  1. Baselines with FreeCAD 0.21 (checks for clean report, no invalid solids)
  2. Tests against FreeCAD 1.0 (compares to 0.21 baseline)
  3. Tests against the pixi dev build (compares to 0.21 baseline)

Results are written back into library_analysis.json under a "version_tests" key.

Usage:
  python Scripts/TestLibraryVersions.py
  python Scripts/TestLibraryVersions.py --resume
  python Scripts/TestLibraryVersions.py --workers 4
  python Scripts/TestLibraryVersions.py --versions 0.21 1.0
  python Scripts/TestLibraryVersions.py --versions dev
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from freecad_binaries import (  # noqa: E402
    FREECAD_PIXI_DIR,
    PORTABLE_BINARIES,
    MACRO_PATH,
)
from metric_types import CompareConfig, MetricDiff  # noqa: E402
from extractors import EXTRACTORS  # noqa: E402
from RunIntegrationTests import compare_maps  # noqa: E402

ANALYSIS_PATH = Path(
    os.environ.get(
        "LIBRARY_ANALYSIS_JSON",
        Path(__file__).resolve().parents[1] / "library_analysis.json",
    )
)

# Default comparison tolerances (same as RunIntegrationTests.py)
DEFAULT_CONFIG = CompareConfig(
    match_percentage=99.99,
    absolute_tolerance=1e-6,
    bbox_tolerance_mm=1.0,
)


def _is_pre_021(program_version: str) -> bool:
    """Check whether a program version string is before 0.21."""
    for prefix in ("0.14", "0.15", "0.16", "0.17", "0.18", "0.19", "0.20"):
        if program_version.startswith(prefix):
            return True
    return False


def _run_freecad_direct(
    freecad_exe: str,
    macro_path: Path,
    fcstd_path: str,
    timeout: float,
) -> Dict[str, Any]:
    """Run EvaluateFile via a direct FreeCADCmd invocation (non-pixi binaries).

    Returns the parsed JSON report dict, or raises on failure.
    """
    outfile = tempfile.mktemp(suffix=".json")
    config_dir = tempfile.mkdtemp()
    try:
        env = {**os.environ, "FREECAD_USER_HOME": config_dir}
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            [freecad_exe, str(macro_path), fcstd_path, "--out", outfile],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            creationflags=creation_flags,
        )
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(f"timeout ({timeout}s)")

        if not os.path.exists(outfile) or os.path.getsize(outfile) == 0:
            raise RuntimeError(
                f"no output (rc={proc.returncode})"
                + (f" stderr: {stderr[-300:]}" if stderr else "")
            )

        with open(outfile, "r", encoding="utf-8") as f:
            report = json.load(f)

        if report.get("schema_version") != 4:
            raise RuntimeError(f"unexpected schema: {report.get('schema_version')}")

        return report
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
        shutil.rmtree(config_dir, ignore_errors=True)


def _get_pixi_shell_hook() -> str:
    """Get the pixi shell-hook script for activating the dev environment."""
    result = subprocess.run(
        ["pixi", "shell-hook"],
        capture_output=True,
        text=True,
        cwd=str(FREECAD_PIXI_DIR),
    )
    if result.returncode != 0:
        raise RuntimeError(f"pixi shell-hook failed: {result.stderr}")
    return result.stdout.strip()


# Module-level cache for pixi shell hook
_pixi_hook_cache: Optional[str] = None


def _get_cached_pixi_hook() -> str:
    global _pixi_hook_cache
    if _pixi_hook_cache is None:
        _pixi_hook_cache = _get_pixi_shell_hook()
    return _pixi_hook_cache


def _run_freecad_pixi(
    macro_path: Path,
    fcstd_path: str,
    timeout: float,
) -> Dict[str, Any]:
    """Run EvaluateFile via pixi-activated FreeCADCmd (dev build).

    Uses environment variables (EVALUATE_FCSTD, EVALUATE_OUT) to pass paths
    to the macro, since pixi run consumes positional arguments.
    """
    outfile = tempfile.mktemp(suffix=".json")
    config_dir = tempfile.mkdtemp()
    try:
        hook = _get_cached_pixi_hook()
        # Build a shell command that activates pixi env and runs FreeCADCmd
        shell_cmd = (
            f"{hook}\n"
            f'export FREECAD_USER_HOME="{config_dir}"\n'
            f'export EVALUATE_FCSTD="{fcstd_path}"\n'
            f'export EVALUATE_OUT="{outfile}"\n'
            f'FreeCADCmd "{macro_path}"'
        )

        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            ["bash", "-c", shell_cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(FREECAD_PIXI_DIR),
            creationflags=creation_flags,
        )
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            proc.wait(timeout=5)
            raise RuntimeError(f"timeout ({timeout}s)")

        if not os.path.exists(outfile) or os.path.getsize(outfile) == 0:
            raise RuntimeError(
                f"no output (rc={proc.returncode})"
                + (f" stderr: {stderr[-300:]}" if stderr else "")
            )

        with open(outfile, "r", encoding="utf-8") as f:
            report = json.load(f)

        if report.get("schema_version") != 4:
            raise RuntimeError(f"unexpected schema: {report.get('schema_version')}")

        return report
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
        shutil.rmtree(config_dir, ignore_errors=True)


def run_evaluation(
    version: str,
    fcstd_path: str,
    program_version: str,
    timeout: float,
) -> Dict[str, Any]:
    """Run EvaluateFile on a file using the specified FreeCAD version.

    Args:
        version: One of "0.21", "1.0", or "dev".
        fcstd_path: Path to the .FCStd file.
        program_version: The file's original ProgramVersion (for Py2 macro selection).
        timeout: Per-file timeout in seconds.

    Returns:
        The parsed v4 JSON report.
    """
    # The Py2 macro is only needed when running on FreeCAD <= 0.17.
    # 0.21, 1.0, and dev all use Python 3.
    macro = MACRO_PATH

    if version == "0.21":
        return _run_freecad_direct(PORTABLE_BINARIES[(0, 21)], macro, fcstd_path, timeout)
    elif version == "1.0":
        return _run_freecad_direct(PORTABLE_BINARIES[(1, 0)], macro, fcstd_path, timeout)
    elif version == "dev":
        return _run_freecad_pixi(macro, fcstd_path, timeout)
    else:
        raise ValueError(f"Unknown version: {version}")


def compare_reports(
    baseline_report: Dict[str, Any],
    new_report: Dict[str, Any],
    config: CompareConfig,
) -> Tuple[bool, int, List[str]]:
    """Compare two v4 reports and return (passed, diff_count, failure_reasons).

    Args:
        baseline_report: The baseline JSON report.
        new_report: The new JSON report to compare.
        config: Tolerance configuration.

    Returns:
        (passed, total_diffs, list_of_failure_reason_strings)
    """
    failures: List[str] = []
    total_diffs = 0

    for section_name, extract_function in EXTRACTORS:
        base_map = extract_function(baseline_report)
        new_map = extract_function(new_report)
        diffs = compare_maps(base_map, new_map, config)
        for diff in diffs:
            if not diff.ok:
                total_diffs += 1
                failures.append(f"{section_name}/{diff.key}: {diff.reason}")

    return len(failures) == 0, total_diffs, failures


def summarize_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Extract summary stats from a v4 report (solid count, invalid count)."""
    solids = report.get("solids", [])
    solid_count = len(solids)
    invalid_count = sum(
        1
        for s in solids
        if isinstance(s, dict)
        and isinstance(s.get("metrics"), dict)
        and s["metrics"].get("is_valid") is False
    )
    return {"solid_count": solid_count, "invalid_solid_count": invalid_count}


def test_file_version(
    entry: Dict[str, Any],
    version: str,
    baseline_report: Optional[Dict[str, Any]],
    timeout: float,
    config: CompareConfig,
) -> Dict[str, Any]:
    """Test a single file against a single FreeCAD version.

    Args:
        entry: The library_analysis entry for the file.
        version: "0.21", "1.0", or "dev".
        baseline_report: The 0.21 baseline report (None when version=="0.21").
        timeout: Per-file timeout.
        config: Comparison tolerances.

    Returns:
        A result dict for this version test.
    """
    fcstd_path = entry["path"]
    program_version = entry.get("program_version", "")
    result: Dict[str, Any] = {"version": version}

    try:
        report = run_evaluation(version, fcstd_path, program_version, timeout)
        summary = summarize_report(report)
        result["solid_count"] = summary["solid_count"]
        result["invalid_solid_count"] = summary["invalid_solid_count"]

        if version == "0.21":
            # Baseline: just check if clean
            result["pass"] = summary["invalid_solid_count"] == 0
            if summary["invalid_solid_count"] > 0:
                result["failure_reason"] = "invalid solids in baseline"
            # Return report for use as baseline by later versions
            result["_report"] = report
        else:
            # Compare against 0.21 baseline
            if baseline_report is None:
                result["pass"] = False
                result["failure_reason"] = "no baseline available"
            else:
                passed, diff_count, failures = compare_reports(baseline_report, report, config)
                result["pass"] = passed
                result["diff_count"] = diff_count
                if not passed:
                    # Keep first 10 failure reasons to avoid bloating the JSON
                    result["failures"] = failures[:10]
                    if len(failures) > 10:
                        result["failures_truncated"] = len(failures)

    except Exception as e:
        result["pass"] = False
        result["error"] = str(e)

    return result


def test_file(
    entry: Dict[str, Any],
    versions: List[str],
    timeout: float,
    config: CompareConfig,
) -> Dict[str, Dict[str, Any]]:
    """Test a file against all requested versions. Returns version_tests dict."""
    version_tests: Dict[str, Dict[str, Any]] = {}
    baseline_report: Optional[Dict[str, Any]] = None

    # Always run 0.21 first if requested (it produces the baseline)
    if "0.21" in versions:
        result = test_file_version(entry, "0.21", None, timeout, config)
        baseline_report = result.pop("_report", None)
        version_tests["0.21"] = result

    # Then run the other versions
    for version in versions:
        if version == "0.21":
            continue
        result = test_file_version(entry, version, baseline_report, timeout, config)
        version_tests[version] = result

    return version_tests


def safe_print(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Test library files across FreeCAD versions.",
    )
    parser.add_argument(
        "--analysis",
        default=str(ANALYSIS_PATH),
        help="Path to library_analysis.json.",
    )
    parser.add_argument(
        "--versions",
        nargs="+",
        default=["0.21", "1.0", "dev"],
        help="FreeCAD versions to test (default: 0.21 1.0 dev).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Per-file per-version timeout in seconds (default: 120).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of parallel file evaluations (default: 1).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip files that already have version_tests results.",
    )
    parser.add_argument(
        "--save-interval",
        type=int,
        default=25,
        help="Save after every N files (default: 25).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Stop after N files (0 = no limit).",
    )
    args = parser.parse_args()

    analysis_path = Path(args.analysis)
    with open(analysis_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    files = data["files"]

    # Filter to pre-0.21 test-suitable files
    candidates = [
        f for f in files if f.get("test_suitable") and _is_pre_021(f.get("program_version", ""))
    ]

    # If resuming, skip files with existing version_tests
    if args.resume:
        needed_versions = set(args.versions)
        to_test = []
        for entry in candidates:
            existing = entry.get("version_tests", {})
            if needed_versions.issubset(existing.keys()):
                continue
            to_test.append(entry)
        skipped = len(candidates) - len(to_test)
        print(f"Resuming: {skipped} already tested, {len(to_test)} remaining")
        candidates = to_test

    if args.limit > 0:
        candidates = candidates[: args.limit]

    total = len(candidates)
    print(f"Testing {total} files against versions: {', '.join(args.versions)}")

    # Pre-cache the pixi hook if dev is requested
    if "dev" in args.versions:
        print("Caching pixi shell-hook...")
        _get_cached_pixi_hook()
        print("Done.")

    done = 0
    passed_counts: Dict[str, int] = {v: 0 for v in args.versions}
    failed_counts: Dict[str, int] = {v: 0 for v in args.versions}
    error_counts: Dict[str, int] = {v: 0 for v in args.versions}

    def process_one(entry: Dict[str, Any]) -> Dict[str, Any]:
        vt = test_file(entry, args.versions, args.timeout, DEFAULT_CONFIG)
        return vt

    if args.workers <= 1:
        # Serial execution
        for entry in candidates:
            vt = process_one(entry)
            # Merge into existing version_tests
            existing_vt = entry.get("version_tests", {})
            existing_vt.update(vt)
            entry["version_tests"] = existing_vt

            done += 1
            # Update counts
            statuses = []
            for v in args.versions:
                r = vt.get(v, {})
                if "error" in r:
                    error_counts[v] += 1
                    statuses.append(f"{v}:ERR")
                elif r.get("pass"):
                    passed_counts[v] += 1
                    statuses.append(f"{v}:OK")
                else:
                    failed_counts[v] += 1
                    statuses.append(f"{v}:FAIL")

            pct = done * 100 // total
            safe_print(
                f"[{pct:3d}%] {done}/{total}  {' '.join(statuses)}  "
                f"{entry.get('relative_path', entry['filename'])}"
            )

            if done % args.save_interval == 0:
                _save(data, analysis_path)
                safe_print(f"  (saved at {done} files)")
    else:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_to_entry = {pool.submit(process_one, entry): entry for entry in candidates}
            for future in as_completed(future_to_entry):
                entry = future_to_entry[future]
                try:
                    vt = future.result()
                except Exception as e:
                    vt = {v: {"pass": False, "error": str(e)} for v in args.versions}

                existing_vt = entry.get("version_tests", {})
                existing_vt.update(vt)
                entry["version_tests"] = existing_vt

                done += 1
                statuses = []
                for v in args.versions:
                    r = vt.get(v, {})
                    if "error" in r:
                        error_counts[v] += 1
                        statuses.append(f"{v}:ERR")
                    elif r.get("pass"):
                        passed_counts[v] += 1
                        statuses.append(f"{v}:OK")
                    else:
                        failed_counts[v] += 1
                        statuses.append(f"{v}:FAIL")

                pct = done * 100 // total
                safe_print(
                    f"[{pct:3d}%] {done}/{total}  {' '.join(statuses)}  "
                    f"{entry.get('relative_path', entry['filename'])}"
                )

                if done % args.save_interval == 0:
                    _save(data, analysis_path)
                    safe_print(f"  (saved at {done} files)")

    # Final save
    _save(data, analysis_path)

    # Summary
    print(f"\n{'=' * 70}")
    print(f"Tested: {done} files")
    print(f"{'Version':<10} {'Pass':>8} {'Fail':>8} {'Error':>8}")
    print("-" * 38)
    for v in args.versions:
        print(f"{v:<10} {passed_counts[v]:>8} {failed_counts[v]:>8} {error_counts[v]:>8}")
    print(f"{'=' * 70}")


def _save(data: Dict[str, Any], path: Path) -> None:
    """Write the analysis data back, adding a version_tests timestamp."""
    data["version_tests_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)
    tmp.replace(path)


if __name__ == "__main__":
    main()
