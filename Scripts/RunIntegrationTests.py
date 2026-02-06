#!/usr/bin/env python3
"""
RunIntegrationTests.py

Runs a FreeCADCmd/freecadcmd metrics script against a folder of .FCStd files,
parses the JSON output, and compares per-solid volumes to baselines with a
fuzzy tolerance expressed as a required "match percentage".

Assumptions about the JSON schema:
- Per-solid entries live under: report["objects"][obj_name]["solids"][i]
- Each solid entry includes: {"object_name": <internal obj.Name>, "index": <int>, "metrics": {"volume_mm3": <float>}}

Baseline JSON files are expected to be named like the .FCStd file stem:
  model.FCStd  ->  <baseline_dir>/model.json

Usage:
  python RunIntegrationTests.py \
    --freecad /path/to/freecadcmd \
    --script  /path/to/EvaluateFile.FCMacro \
    --fcstd-dir /path/to/fcstds \
    --baseline-dir /path/to/baselines \
    --match-pct 99.999 \
    --abs-tol-mm3 1e-9

Exit codes:
  0 = all comparisons within tolerance
  2 = mismatches found
  3 = execution / I/O errors (missing files, FreeCAD failed, invalid JSON)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple, List, Any, Optional


SolidKey = Tuple[str, int]  # (object_name, index)


@dataclass(frozen=True)
class CompareConfig:
    match_pct: float          # e.g. 99.999
    abs_tol_mm3: float        # absolute floor tolerance for very small volumes


@dataclass
class SolidDiff:
    key: SolidKey
    baseline: Optional[float]
    new: Optional[float]
    rel_err: Optional[float]
    ok: bool
    reason: str


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Regression-compare FreeCAD solid volumes vs baselines (JSON).")
    p.add_argument("--freecad", required=True, help="Path to FreeCADCmd/freecadcmd executable")
    p.add_argument("--script", required=True, help="Path to the FreeCAD JSON-emitting macro file (EvaluateFile.FCMacro)")
    p.add_argument("--fcstd-dir", required=True, help="Folder containing .FCStd files")
    p.add_argument("--baseline-dir", required=True, help="Folder containing baseline JSON files (stem-matched)")
    p.add_argument("--match-pct", type=float, default=99.999,
                   help="Required match percentage. 99.999 => relative tolerance = 1 - 0.99999 = 1e-5")
    p.add_argument("--abs-tol-mm3", type=float, default=1e-9,
                   help="Absolute tolerance in mm^3 used as a floor near zero (default: 1e-9)")
    p.add_argument("--recursive", action="store_true", help="Recurse into subfolders of fcstd-dir")
    p.add_argument("--timeout", type=float, default=300.0, help="Per-file FreeCAD run timeout seconds (default: 300)")
    p.add_argument("--verbose", action="store_true", help="Print per-file diffs (otherwise only summary + failures)")
    return p.parse_args(argv)


def required_rel_tol(match_pct: float) -> float:
    """
    Convert "match percentage" to relative tolerance.
    Example: 99.999% match -> allowed relative difference = 1 - 0.99999 = 1e-5
    """
    if not (0.0 < match_pct <= 100.0):
        raise ValueError("match_pct must be in (0, 100].")
    return 1.0 - (match_pct / 100.0)


def run_freecad_script(
    freecad_exe: Path,
    script_path: Path,
    fcstd_path: Path,
    timeout_s: float
) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory()  as temp_dir:
        output_file = os.path.join(temp_dir, "output.json")
        cmd = [str(freecad_exe), str(script_path), str(fcstd_path), "--out", output_file]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"FreeCAD run failed (rc={proc.returncode}) for {fcstd_path}\n"
                f"STDERR:\n{proc.stderr.strip()}\n\n"
                f"STDOUT (first 2000 chars):\n{proc.stdout[:2000].strip()}"
            )
        
        with open (output_file, "r", encoding="utf-8") as f:
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
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_volumes(report: Dict[str, Any]) -> Dict[SolidKey, float]:
    """
    Returns mapping (object_name, index) -> volume_mm3
    """
    out: Dict[SolidKey, float] = {}

    objects = report.get("objects", {})
    if not isinstance(objects, dict):
        return out

    for obj_name, obj_entry in objects.items():
        if not isinstance(obj_entry, dict):
            continue
        solids = obj_entry.get("solids", [])
        if not isinstance(solids, list):
            continue

        for s in solids:
            if not isinstance(s, dict):
                continue
            object_name = s.get("object_name") or obj_name
            idx = s.get("index")
            metrics = s.get("metrics", {})
            if not isinstance(metrics, dict):
                continue
            vol = metrics.get("volume_mm3")

            if isinstance(object_name, str) and isinstance(idx, int) and isinstance(vol, (int, float)):
                out[(object_name, idx)] = float(vol)

    return out


def compare_maps(
    baseline: Dict[SolidKey, float],
    new: Dict[SolidKey, float],
    cfg: CompareConfig
) -> List[SolidDiff]:
    rel_tol = required_rel_tol(cfg.match_pct)

    diffs: List[SolidDiff] = []

    all_keys = set(baseline.keys()) | set(new.keys())
    for key in sorted(all_keys, key=lambda k: (k[0], k[1])):
        b = baseline.get(key)
        n = new.get(key)

        if b is None:
            diffs.append(SolidDiff(key=key, baseline=None, new=n, rel_err=None, ok=False, reason="missing_in_baseline"))
            continue
        if n is None:
            diffs.append(SolidDiff(key=key, baseline=b, new=None, rel_err=None, ok=False, reason="missing_in_new"))
            continue

        # Fuzzy compare: pass if |n-b| <= max(abs_tol, rel_tol*max(|b|,|n|))
        denom = max(abs(b), abs(n))
        tol = max(cfg.abs_tol_mm3, rel_tol * denom)
        err = abs(n - b)

        ok = err <= tol
        rel_err = (err / denom) if denom > 0 else (0.0 if err == 0 else math.inf)

        diffs.append(
            SolidDiff(
                key=key,
                baseline=b,
                new=n,
                rel_err=rel_err,
                ok=ok,
                reason="ok" if ok else "volume_mismatch",
            )
        )

    return diffs


def find_fcstd_files(root: Path, recursive: bool) -> List[Path]:
    if recursive:
        return sorted([p for p in root.rglob("*.FCStd") if p.is_file()])
    return sorted([p for p in root.glob("*.FCStd") if p.is_file()])


def main(argv: List[str]) -> int:
    args = parse_args(argv)

    freecad_exe = Path(args.freecad)
    script_path = Path(args.script)
    fcstd_dir = Path(args.fcstd_dir)
    baseline_dir = Path(args.baseline_dir)

    for p in (freecad_exe, script_path, fcstd_dir, baseline_dir):
        if not p.exists():
            print(f"ERROR: Path does not exist: {p}", file=sys.stderr)
            return 3

    cfg = CompareConfig(match_pct=float(args.match_pct), abs_tol_mm3=float(args.abs_tol_mm3))

    fcstd_files = find_fcstd_files(fcstd_dir, args.recursive)
    if not fcstd_files:
        print(f"ERROR: No .FCStd files found in: {fcstd_dir}", file=sys.stderr)
        return 3

    total_files = 0
    ok_files = 0
    mismatch_files = 0
    error_files = 0

    for fcstd_path in fcstd_files:
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

            new_map = extract_volumes(new_report)
            base_map = extract_volumes(base_report)

            diffs = compare_maps(base_map, new_map, cfg)
            bad = [d for d in diffs if not d.ok]

            if bad:
                mismatch_files += 1
                print(f"[FAIL] {fcstd_path.name}: {len(bad)} issue(s)")
                for d in bad:
                    if d.reason in ("missing_in_baseline", "missing_in_new"):
                        print(f"  - {d.reason}: {d.key}")
                    else:
                        rel_pct = (d.rel_err * 100.0) if (d.rel_err is not None and math.isfinite(d.rel_err)) else None
                        rel_str = f"{rel_pct:.9f}%" if rel_pct is not None else "inf"
                        print(
                            f"  - mismatch {d.key}: baseline={d.baseline:.12g} new={d.new:.12g} "
                            f"rel_err={rel_str} (required match >= {cfg.match_pct}%)"
                        )
                if args.verbose:
                    print(f"  solids compared: {len(diffs)} (ok={len(diffs)-len(bad)} bad={len(bad)})")
            else:
                ok_files += 1
                if args.verbose:
                    print(f"[OK]   {fcstd_path.name}: solids={len(diffs)}")

        except subprocess.TimeoutExpired:
            error_files += 1
            print(f"[ERROR] {fcstd_path.name}: timed out after {args.timeout}s", file=sys.stderr)
        except Exception as e:
            error_files += 1
            print(f"[ERROR] {fcstd_path.name}: {e}", file=sys.stderr)

    print("\n" + 35*"=" + " Summary " + 35*"=")
    print(f"Files checked: {total_files}")
    print(f"OK:            {ok_files}")
    print(f"Mismatched:    {mismatch_files}")
    print(f"Errors:        {error_files}")
    print(f"Match pct:     {cfg.match_pct} (rel_tol={required_rel_tol(cfg.match_pct):.12g})")
    print(f"Abs tol mm^3:  {cfg.abs_tol_mm3:.12g}")
    print(79*"=")

    if mismatch_files or error_files:
        print ("Integration tests failed")
    else:
        print ("Integration tests passed")

    if error_files > 0:
        return 3
    if mismatch_files > 0:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))