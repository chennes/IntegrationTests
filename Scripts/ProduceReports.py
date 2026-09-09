#!/usr/bin/env python3
"""ProduceReports.py

Run the evaluation macro over a list of FCStd files with ONE FreeCAD binary and
write a v4 JSON report per file, plus an index of per-file outcomes. This is
the "produce reports" half of a compare workflow, split out so it can run on a
machine that has only the binary, the macro, and the files -- no baselines, no
index database, and no assumptions about how files are named or where they
came from.

Input manifest (--files-from) is JSON: {"files": [{"id": "<unique id>",
"file": "<path relative to --file-root>"}, ...]}. Reports are written to
--out-dir/<id>.json; the summary lands in --out-dir/index.json as
{"results": {id: {"ok": bool, "error": str|null, "runtime_s": float}}}.

--arg-style controls how the macro receives its input and output paths:
  positional  (default) FreeCADCmd <macro> <fcstd> --out <report>  -- correct
              for portable/release binaries, which pass arguments through.
  env         EVALUATE_FCSTD/EVALUATE_OUT environment variables -- required
              for pixi-environment dev builds, whose FreeCADCmd consumes
              positional file arguments itself (see CLAUDE.md).

Exit codes: 0 = every file produced a report, 2 = some files failed (details
in index.json), 3 = setup error.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--freecad", required=True, help="FreeCADCmd binary")
    p.add_argument("--script", required=True, help="EvaluateFile macro path")
    p.add_argument("--files-from", required=True, help="Manifest JSON (see module docstring)")
    p.add_argument("--file-root", required=True, help="Directory manifest paths are relative to")
    p.add_argument("--out-dir", required=True, help="Directory for per-file reports + index.json")
    p.add_argument("--timeout", type=float, default=120.0, help="Per-file timeout in seconds")
    p.add_argument("--workers", type=int, default=6, help="Parallel FreeCAD processes")
    p.add_argument("--arg-style", choices=("positional", "env"), default="positional")
    return p.parse_args(argv)


def run_macro(
    freecad_exe: Path,
    script_path: Path,
    fcstd_path: Path,
    timeout_s: float,
    arg_style: str,
) -> Dict[str, Any]:
    """Run the macro on one file and return the parsed report; raises on failure."""
    tmpdir = tempfile.mkdtemp(prefix="produce_reports_")
    try:
        out_path = Path(tmpdir) / "output.json"
        env = os.environ.copy()
        # Isolated config dir so runs never touch (or depend on) a user config.
        env["FREECAD_USER_HOME"] = tmpdir
        if arg_style == "env":
            env["EVALUATE_FCSTD"] = str(fcstd_path)
            env["EVALUATE_OUT"] = str(out_path)
            cmd = [str(freecad_exe), str(script_path)]
        else:
            cmd = [str(freecad_exe), str(script_path), str(fcstd_path), "--out", str(out_path)]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, env=env)
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()
            raise RuntimeError(
                f"FreeCADCmd exited {proc.returncode}: {tail[-1] if tail else 'no output'}"
            )
        if not out_path.is_file():
            raise RuntimeError("macro produced no output file")
        report = json.loads(out_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise RuntimeError("macro output is not a JSON object")
        return report
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    freecad_exe = Path(args.freecad)
    script_path = Path(args.script)
    file_root = Path(args.file_root)
    out_dir = Path(args.out_dir)
    manifest_path = Path(args.files_from)
    for label, path in [
        ("freecad", freecad_exe),
        ("script", script_path),
        ("file-root", file_root),
        ("files-from", manifest_path),
    ]:
        if not path.exists():
            print(f"ERROR: {label} path does not exist: {path}", file=sys.stderr)
            return 3
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest.get("files", [])
    if not entries:
        print("ERROR: manifest lists no files", file=sys.stderr)
        return 3

    results: Dict[str, Dict[str, Any]] = {}

    def one(entry: Dict[str, Any]) -> None:
        entry_id = str(entry["id"])
        fcstd = file_root / entry["file"]
        started = time.monotonic()
        error: Optional[str] = None
        if not fcstd.is_file():
            error = "file not found"
        else:
            try:
                report = run_macro(freecad_exe, script_path, fcstd, args.timeout, args.arg_style)
                report_path = out_dir / f"{entry_id}.json"
                report_path.write_text(
                    json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
                )
            except subprocess.TimeoutExpired:
                error = f"timeout after {args.timeout}s"
            except Exception as e:
                msg = str(e)
                error = msg.splitlines()[0] if msg.strip() else type(e).__name__
        results[entry_id] = {
            "ok": error is None,
            "error": error,
            "runtime_s": round(time.monotonic() - started, 2),
        }

    print(f"Evaluating {len(entries)} files with {freecad_exe.name} (workers={args.workers})")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(one, e) for e in entries]
        done = 0
        for fut in as_completed(futures):
            fut.result()
            done += 1
            if done % 25 == 0 or done == len(entries):
                n_bad = sum(1 for r in results.values() if not r["ok"])
                print(f"  [{done}/{len(entries)}] {n_bad} failed so far")

    index = {"results": results, "n_files": len(entries)}
    (out_dir / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    n_failed = sum(1 for r in results.values() if not r["ok"])
    print(
        f"Done: {len(results) - n_failed} ok, {n_failed} failed; index at {out_dir / 'index.json'}"
    )
    return 2 if n_failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
