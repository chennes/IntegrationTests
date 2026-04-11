#!/usr/bin/env python3
"""Check whether an FCStd file is suitable for the integration test suite.

Evaluates a single file by:
  1. Extracting metadata (version, license, author) from the FCStd archive.
  2. Running EvaluateFile.FCMacro with the FreeCAD version that created the file.
  3. Running EvaluateFile.FCMacro with the latest dev build.
  4. Checking that all solids are valid and all sketches solved in both runs.

The result is one of:
  - REJECTED:    The file fails in its native FreeCAD version (invalid solids,
                 unsolved sketches, missing license, etc.) and is not suitable.
  - ACCEPTED:    Both native and dev builds produce clean results.
  - REGRESSION:  Clean in native version but broken in dev -- worth investigating.

Usage:
  python Scripts/CheckFCStdForSuitability.py path/to/file.FCStd
  python Scripts/CheckFCStdForSuitability.py path/to/file.FCStd --skip-dev
  python Scripts/CheckFCStdForSuitability.py path/to/file.FCStd --timeout 120

Exit codes:
  0 -- ACCEPTED
  1 -- REJECTED (file is not suitable)
  2 -- REGRESSION (native OK, dev broken)
  3 -- error (missing binary, timeout, etc.)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent

sys.path.insert(0, str(SCRIPT_DIR))

from AnalyzeLibrary import extract_fcstd_metadata  # noqa: E402
from freecad_binaries import (  # noqa: E402
    FREECAD_PIXI_DIR,
    MACRO_PATH,
    MACRO_PATH_PY2,
    needs_py2,
    parse_version,
    resolve_freecad,
)
from license_utils import is_incompatible, is_placeholder, normalize_license  # noqa: E402


def run_evaluation(
    fcstd_path: Path,
    freecad_exe: str,
    macro_path: Path,
    timeout: float,
) -> Dict[str, Any]:
    """Run EvaluateFile.FCMacro on a file and return the parsed JSON report.

    Args:
        fcstd_path: Path to the .FCStd file.
        freecad_exe: Path to FreeCADCmd executable.
        macro_path: Path to the macro to use.
        timeout: Timeout in seconds.

    Returns:
        Dict with "ok" bool, "report" (the parsed JSON if successful),
        and "error" string on failure.
    """
    outfile = tempfile.mktemp(suffix=".json")
    config_dir = tempfile.mkdtemp()

    try:
        env = {**os.environ, "FREECAD_USER_HOME": config_dir}
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            [freecad_exe, str(macro_path), str(fcstd_path), "--out", outfile],
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
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return {"ok": False, "error": f"timeout ({timeout}s)"}

        if proc.returncode != 0:
            tail = stderr[-500:] if stderr else "(no stderr)"
            return {"ok": False, "error": f"exit code {proc.returncode}: {tail}"}

        if not os.path.exists(outfile) or os.path.getsize(outfile) == 0:
            return {"ok": False, "error": "no output file produced"}

        with open(outfile, "r", encoding="utf-8") as f:
            report = json.load(f)

        return {"ok": True, "report": report}

    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"invalid JSON: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
        shutil.rmtree(config_dir, ignore_errors=True)


def run_evaluation_pixi(
    fcstd_path: Path,
    macro_path: Path,
    timeout: float,
) -> Dict[str, Any]:
    """Run EvaluateFile.FCMacro via pixi-activated FreeCADCmd (dev build).

    Args:
        fcstd_path: Path to the .FCStd file.
        macro_path: Path to the macro to use.
        timeout: Timeout in seconds.

    Returns:
        Dict with "ok" bool, "report" (the parsed JSON if successful),
        and "error" string on failure.
    """
    outfile = tempfile.mktemp(suffix=".json")
    config_dir = tempfile.mkdtemp()

    try:
        hook_result = subprocess.run(
            ["pixi", "shell-hook"],
            capture_output=True,
            text=True,
            cwd=str(FREECAD_PIXI_DIR),
        )
        if hook_result.returncode != 0:
            return {"ok": False, "error": f"pixi shell-hook failed: {hook_result.stderr}"}
        hook = hook_result.stdout.strip()

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
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return {"ok": False, "error": f"timeout ({timeout}s)"}

        if proc.returncode != 0:
            tail = stderr[-500:] if stderr else "(no stderr)"
            return {"ok": False, "error": f"exit code {proc.returncode}: {tail}"}

        if not os.path.exists(outfile) or os.path.getsize(outfile) == 0:
            return {"ok": False, "error": "no output file produced"}

        with open(outfile, "r", encoding="utf-8") as f:
            report = json.load(f)

        return {"ok": True, "report": report}

    except json.JSONDecodeError as e:
        return {"ok": False, "error": f"invalid JSON: {e}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
        shutil.rmtree(config_dir, ignore_errors=True)


def check_report_health(report: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check that all solids are valid and all sketches are solved.

    Args:
        report: Parsed JSON report from EvaluateFile.FCMacro.

    Returns:
        (all_ok, list_of_problem_strings)
    """
    problems: List[str] = []

    solids = report.get("solids", [])
    if not solids:
        problems.append("No solids found in report")

    for entry in solids:
        name = entry.get("_source_name", "?")
        metrics = entry.get("metrics", {})
        if not metrics.get("is_valid", False):
            problems.append(f"Solid '{name}' is invalid")

    for entry in report.get("sketches", []):
        name = entry.get("_source_name", "?")
        metrics = entry.get("metrics", {})
        if not metrics.get("is_valid", False):
            problems.append(f"Sketch '{name}' is not solved")

    return len(problems) == 0, problems


def check_metadata(meta: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Check license and author metadata for test suite suitability.

    Args:
        meta: Metadata dict from extract_fcstd_metadata.

    Returns:
        (all_ok, list_of_problem_strings)
    """
    problems: List[str] = []

    license_str = meta.get("license", "")
    if not license_str or is_placeholder(license_str):
        problems.append("No license set (FreeCAD default 'All rights reserved')")
    elif is_incompatible(license_str):
        problems.append(f"Incompatible license: '{license_str}'")
    else:
        spdx = normalize_license(license_str)
        if spdx is None:
            problems.append(f"Unrecognized license: '{license_str}'")

    if not meta.get("createdby", ""):
        problems.append("No author (CreatedBy) set in file metadata")

    return len(problems) == 0, problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check whether an FCStd file is suitable for the integration test suite.",
    )
    parser.add_argument(
        "fcstd",
        help="Path to the .FCStd file to check.",
    )
    parser.add_argument(
        "--skip-dev",
        action="store_true",
        help="Skip the dev build evaluation (only test with the native version).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        help="Per-evaluation FreeCAD timeout in seconds (default: 300).",
    )
    args = parser.parse_args()

    fcstd_path = Path(args.fcstd).resolve()
    if not fcstd_path.is_file():
        print(f"ERROR: File not found: {fcstd_path}", file=sys.stderr)
        return 3

    print(f"File: {fcstd_path.name}")
    print()

    # --- Step 1: Metadata ---
    print("Checking metadata...")
    meta = extract_fcstd_metadata(fcstd_path)
    version_str = meta.get("program_version", "unknown")
    print(f"  FreeCAD version: {version_str}")
    print(f"  License: {meta.get('license', '') or '(none)'}")
    print(f"  Author: {meta.get('createdby', '') or '(none)'}")
    print(f"  File size: {meta.get('file_size_mb', '?')} MB")

    meta_ok, meta_problems = check_metadata(meta)
    if not meta_ok:
        print()
        print("REJECTED -- metadata problems:")
        for p in meta_problems:
            print(f"  - {p}")
        return 1

    spdx = normalize_license(meta.get("license", ""))
    print(f"  SPDX: {spdx}")
    print()

    # --- Step 2: Resolve native binary ---
    freecad_exe, resolution = resolve_freecad(version_str)
    if freecad_exe is None or not Path(freecad_exe).is_file():
        print(f"ERROR: No FreeCAD binary available for version {version_str}", file=sys.stderr)
        return 3

    use_py2 = needs_py2(version_str)
    macro = MACRO_PATH_PY2 if use_py2 else MACRO_PATH
    print(f"Native evaluation ({resolution})...")
    if use_py2:
        print(f"  Using Python 2 macro for FreeCAD {version_str}")

    # --- Step 3: Run native evaluation ---
    native_result = run_evaluation(fcstd_path, freecad_exe, macro, args.timeout)
    if not native_result["ok"]:
        print(f"  ERROR: {native_result['error']}")
        print()
        print("REJECTED -- native evaluation failed")
        return 1

    native_ok, native_problems = check_report_health(native_result["report"])
    native_solids = len(native_result["report"].get("solids", []))
    native_sketches = len(native_result["report"].get("sketches", []))
    print(f"  Solids: {native_solids}, Sketches: {native_sketches}")

    if not native_ok:
        print()
        print("REJECTED -- problems in native version:")
        for p in native_problems:
            print(f"  - {p}")
        return 1

    print("  All solids valid, all sketches solved")
    print()

    # --- Step 4: Dev build evaluation ---
    if args.skip_dev:
        print("Skipping dev build evaluation (--skip-dev)")
        print()
        print("ACCEPTED (native only)")
        return 0

    print("Dev build evaluation (pixi)...")
    dev_result = run_evaluation_pixi(fcstd_path, MACRO_PATH, args.timeout)
    if not dev_result["ok"]:
        print(f"  ERROR: {dev_result['error']}")
        print()
        print("REGRESSION -- native OK, dev evaluation failed")
        return 2

    dev_ok, dev_problems = check_report_health(dev_result["report"])
    dev_solids = len(dev_result["report"].get("solids", []))
    dev_sketches = len(dev_result["report"].get("sketches", []))
    print(f"  Solids: {dev_solids}, Sketches: {dev_sketches}")

    if not dev_ok:
        print()
        print("REGRESSION -- problems in dev build:")
        for p in dev_problems:
            print(f"  - {p}")
        return 2

    print("  All solids valid, all sketches solved")
    print()
    print("ACCEPTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
