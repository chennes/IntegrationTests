#!/usr/bin/env python3
"""Analyze a directory tree of FCStd files for integration test suitability.

Walks a directory tree, inspects each .FCStd file's metadata (version, license,
author, size), determines the best available FreeCAD binary for evaluation,
runs a full touch-recompute via EvaluateFile.FCMacro, and records the results
to a JSON analysis file.

Usage:
  python Scripts/AnalyzeLibrary.py G:\\FreeCAD\\FreeCAD-library
  python Scripts/AnalyzeLibrary.py G:\\FreeCAD\\FreeCAD-library --output analysis.json
  python Scripts/AnalyzeLibrary.py G:\\FreeCAD\\FreeCAD-library --max-size 10
  python Scripts/AnalyzeLibrary.py G:\\FreeCAD\\FreeCAD-library --resume

Requires: 7-Zip (at "C:\\Program Files\\7-Zip\\7z.exe" or on PATH)
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from freecad_binaries import (
    PORTABLE_BINARIES,
    MACRO_PATH,
    MACRO_PATH_PY2,
    PY2_VERSIONS,
    parse_version,
    resolve_freecad,
)


def safe_print(msg: str, **kwargs: Any) -> None:
    """Print a string, replacing unencodable characters with '?' for the console.

    Args:
        msg: The message to print.
        **kwargs: Passed through to print().
    """
    try:
        print(msg, **kwargs)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"), **kwargs)


def extract_fcstd_metadata(path: Path) -> Dict[str, Any]:
    """Extract metadata from an FCStd file without opening it in FreeCAD.

    Args:
        path: Path to the .FCStd file.

    Returns:
        Dict with version, license, author, comment, and Draft/feature type info.
    """
    meta: Dict[str, Any] = {
        "file_size_bytes": path.stat().st_size,
        "file_size_mb": round(path.stat().st_size / (1024 * 1024), 2),
    }

    try:
        with zipfile.ZipFile(path, "r") as z:
            if "Document.xml" not in z.namelist():
                meta["error"] = "no Document.xml"
                return meta
            with z.open("Document.xml") as dx:
                content = dx.read().decode("utf-8", errors="replace")

            # ProgramVersion
            m = re.search(r'ProgramVersion="([^"]+)"', content)
            meta["program_version"] = m.group(1) if m else "unknown"

            # String properties
            for prop in ("CreatedBy", "License", "LicenseURL", "Comment"):
                pm = re.search(
                    rf'name="{prop}".*?<String value="([^"]*?)"',
                    content,
                    re.DOTALL,
                )
                meta[prop.lower()] = pm.group(1) if pm else ""

            # Object types
            obj_types = re.findall(r'<Object\s+type="([^"]+)"', content)
            meta["object_type_counts"] = {}
            for t in obj_types:
                meta["object_type_counts"][t] = meta["object_type_counts"].get(t, 0) + 1
            meta["object_count"] = len(obj_types)

            # Draft module usage
            draft_modules = sorted(set(re.findall(r'module="(draftobjects\.\w+)"', content)))
            meta["draft_modules"] = draft_modules

            # Python proxy modules (broader)
            proxy_modules = sorted(set(re.findall(r'module="(\w+(?:\.\w+)*)"', content)))
            meta["python_modules"] = proxy_modules

    except Exception as e:
        meta["error"] = str(e)

    return meta


def evaluate_file(
    fcstd_path: Path,
    freecad_exe: str,
    timeout: float = 120.0,
    macro_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run EvaluateFile.FCMacro on a file and return the summary.

    Args:
        fcstd_path: Path to the .FCStd file.
        freecad_exe: Path to FreeCADCmd executable.
        timeout: Timeout in seconds.
        macro_path: Path to the macro to use.  Defaults to MACRO_PATH.

    Returns:
        Dict with evaluation results: solid counts, invalid counts, section
        summaries, etc.
    """
    if macro_path is None:
        macro_path = MACRO_PATH
    result: Dict[str, Any] = {}
    outfile = tempfile.mktemp(suffix=".json")
    config_dir = tempfile.mkdtemp()

    try:
        env = {**os.environ, "FREECAD_USER_HOME": config_dir}
        # CREATE_NEW_PROCESS_GROUP so we can kill the entire tree on timeout
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
                # taskkill /T /F kills the entire process tree reliably
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                )
            else:
                proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass  # best effort -- the process may already be gone
            result["recompute_ok"] = False
            result["error"] = f"timeout ({timeout}s)"
            return result

        result["exit_code"] = proc.returncode
        result["recompute_ok"] = proc.returncode == 0

        if not os.path.exists(outfile) or os.path.getsize(outfile) == 0:
            result["recompute_ok"] = False
            result["error"] = "no output file"
            if stderr:
                result["stderr_tail"] = stderr[-500:]
            return result

        with open(outfile, "r", encoding="utf-8") as f:
            report = json.load(f)

        result["schema_version"] = report.get("schema_version")

        # Summarize each section
        sections: Dict[str, Dict[str, int]] = {}
        for key, val in report.items():
            if key in ("schema_version", "source"):
                continue
            if not isinstance(val, list):
                continue
            total = len(val)
            invalid = 0
            for entry in val:
                if isinstance(entry, dict):
                    metrics = entry.get("metrics", {})
                    if isinstance(metrics, dict) and metrics.get("is_valid") is False:
                        invalid += 1
            sections[key] = {"count": total, "invalid": invalid}
        result["sections"] = sections

        # Solid-specific summary
        solids = report.get("solids", [])
        result["solid_count"] = len(solids)
        result["invalid_solid_count"] = sum(
            1
            for s in solids
            if isinstance(s, dict)
            and isinstance(s.get("metrics"), dict)
            and s["metrics"].get("is_valid") is False
        )

        # Total metric count (for sizing)
        total_metrics = sum(s.get("count", 0) for s in sections.values())
        result["total_metric_entries"] = total_metrics

    except json.JSONDecodeError as e:
        result["recompute_ok"] = False
        result["error"] = f"invalid JSON: {e}"
    except Exception as e:
        result["recompute_ok"] = False
        result["error"] = str(e)
    finally:
        if os.path.exists(outfile):
            os.unlink(outfile)
        shutil.rmtree(config_dir, ignore_errors=True)

    return result


def _prepare_entry(
    fcstd_path: Path,
    root: Path,
    max_size: float,
) -> Dict[str, Any]:
    """Build a file entry with metadata and resolve the FreeCAD binary.

    This runs quickly (no FreeCAD subprocess) and is always done in the main thread.

    Args:
        fcstd_path: Path to the .FCStd file.
        root: Root directory for computing relative paths.
        max_size: Maximum file size in MB for evaluation.

    Returns:
        A dict with metadata, binary resolution, and a "needs_eval" flag.
    """
    rel_path = str(fcstd_path.relative_to(root))
    entry: Dict[str, Any] = {
        "path": str(fcstd_path),
        "relative_path": rel_path,
        "filename": fcstd_path.name,
    }

    meta = extract_fcstd_metadata(fcstd_path)
    entry.update(meta)

    version_str = meta.get("program_version", "unknown")
    entry["version_parsed"] = version_str
    freecad_exe, resolution = resolve_freecad(version_str)
    entry["binary_resolution"] = resolution

    if meta.get("file_size_mb", 999) > max_size:
        entry["skipped_reason"] = f"file too large ({meta.get('file_size_mb', '?')} MB)"
    elif freecad_exe is None:
        entry["skipped_reason"] = "no FreeCAD binary available"
    elif "error" in meta:
        entry["skipped_reason"] = f"metadata error: {meta['error']}"
    else:
        entry["_freecad_exe"] = freecad_exe
        entry["_needs_eval"] = True
        # Pick the Py2 macro for old FreeCAD versions that ship Python 2
        parsed = parse_version(version_str)
        if parsed and parsed in PY2_VERSIONS:
            entry["_macro_path"] = str(MACRO_PATH_PY2)

    return entry


def _evaluate_entry(
    entry: Dict[str, Any],
    timeout: float,
    max_size: float,
) -> Dict[str, Any]:
    """Evaluate a single file entry by running FreeCAD.  Safe to call from a worker thread.

    Args:
        entry: A file entry dict from _prepare_entry with "_needs_eval" set.
        timeout: Per-file timeout in seconds.
        max_size: Maximum file size in MB for test suitability.

    Returns:
        The entry dict, updated with evaluation results.
    """
    fcstd_path = Path(entry["path"])
    freecad_exe = entry.pop("_freecad_exe")
    entry.pop("_needs_eval", None)
    macro_path_str = entry.pop("_macro_path")
    macro_path = Path(macro_path_str)

    eval_result = evaluate_file(fcstd_path, freecad_exe, timeout=timeout, macro_path=macro_path)
    entry["evaluation"] = eval_result

    ok = eval_result.get("recompute_ok", False)
    solids = eval_result.get("solid_count", 0)
    invalid = eval_result.get("invalid_solid_count", 0)
    entry["test_suitable"] = (
        ok and invalid == 0 and solids > 0 and entry.get("file_size_mb", 999) <= max_size
    )
    return entry


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analyze FCStd files for integration test suitability.",
    )
    parser.add_argument(
        "directory",
        help="Root directory to scan for .FCStd files.",
    )
    parser.add_argument(
        "--output",
        "-o",
        default="library_analysis.json",
        help="Output JSON file (default: library_analysis.json).",
    )
    parser.add_argument(
        "--max-size",
        type=float,
        default=5.0,
        help="Only evaluate files smaller than this (MB). Larger files get metadata only.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="Per-file FreeCAD evaluation timeout in seconds (default: 60).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing output file, skipping already-analyzed files.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Number of parallel FreeCAD evaluations (default: 8).",
    )
    args = parser.parse_args()

    root = Path(args.directory)
    if not root.is_dir():
        print(f"ERROR: Not a directory: {root}", file=sys.stderr)
        sys.exit(1)

    output_path = Path(args.output)

    # Load existing results for --resume
    existing: Dict[str, Any] = {}
    if args.resume and output_path.is_file():
        with open(output_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("files", []):
            existing[entry["path"]] = entry
        print(f"Resuming: {len(existing)} files already analyzed")

    # Find all FCStd files
    all_files = sorted(root.rglob("*.FCStd"))
    print(f"Found {len(all_files)} .FCStd files in {root}")

    # Phase 1: prepare entries (fast, serial -- resolves binaries once)
    results: List[Dict[str, Any]] = []
    to_evaluate: List[Dict[str, Any]] = []
    skipped = 0
    for fcstd_path in all_files:
        abs_path = str(fcstd_path)
        if abs_path in existing:
            results.append(existing[abs_path])
            skipped += 1
            continue
        entry = _prepare_entry(fcstd_path, root, args.max_size)
        if entry.get("_needs_eval"):
            to_evaluate.append(entry)
        else:
            results.append(entry)

    print(
        f"To evaluate: {len(to_evaluate)} | Skipped (size/error): "
        f"{len(all_files) - len(to_evaluate) - skipped} | Resumed: {skipped}"
    )

    # Phase 2: evaluate in parallel
    from concurrent.futures import ThreadPoolExecutor, as_completed

    done = 0
    errors = 0

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_evaluate_entry, entry, args.timeout, args.max_size): entry
            for entry in to_evaluate
        }
        for future in as_completed(futures):
            done += 1
            entry = future.result()
            results.append(entry)

            eval_result = entry.get("evaluation", {})
            ok = eval_result.get("recompute_ok", False)
            solids = eval_result.get("solid_count", 0)
            invalid = eval_result.get("invalid_solid_count", 0)

            if not ok:
                errors += 1
                err = eval_result.get("error", f"rc={eval_result.get('exit_code', '?')}")
                status = f"FAIL ({err})"
            elif invalid > 0:
                status = f"OK ({solids} solids, {invalid} INVALID)"
            else:
                status = f"OK ({solids} solids)"

            pct = done * 100 // len(to_evaluate) if to_evaluate else 100
            safe_print(f"[{pct:3d}%] {done}/{len(to_evaluate)} {entry['relative_path']}  {status}")

            # Periodic save
            if done % 50 == 0:
                _save_output(output_path, results, root, args)

    _save_output(output_path, results, root, args)

    # Summary
    total = len(results)
    evaluated = sum(1 for r in results if "evaluation" in r)
    suitable = sum(1 for r in results if r.get("test_suitable", False))
    with_draft = sum(1 for r in results if r.get("draft_modules"))
    print(f"\n{'='*60}")
    print(f"Analyzed:    {evaluated} files ({skipped} resumed)")
    print(f"Errors:      {errors}")
    print(f"Total:       {total}")
    print(f"Test-suitable: {suitable}")
    print(f"With Draft:  {with_draft}")
    print(f"Output:      {output_path}")
    print(f"{'='*60}")


def _save_output(
    output_path: Path,
    results: List[Dict[str, Any]],
    root: Path,
    args: argparse.Namespace,
) -> None:
    """Write the analysis results to the output file.

    Args:
        output_path: Where to write the JSON.
        results: List of per-file result dicts.
        root: The root directory that was scanned.
        args: Parsed CLI arguments.
    """
    output = {
        "analysis_date": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "root_directory": str(root),
        "max_size_mb": args.max_size,
        "timeout_s": args.timeout,
        "file_count": len(results),
        "files": results,
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)


if __name__ == "__main__":
    main()
