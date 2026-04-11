# Scripts Reference

This document describes each script in the integration test suite, what it does, and how to call it.

---

## Executable Scripts

### RunIntegrationTests.py

The main test harness. For each `.FCStd` file in the test directory, it spawns FreeCADCmd with the evaluation macro, reads the JSON output, and compares it against baseline results.

Example invocation:
```
cd G:/FreeCAD/FreeCAD && eval "$(pixi shell-hook)" && python G:/FreeCAD/IntegrationTests/Scripts/RunIntegrationTests.py --freecad G:/FreeCAD/FreeCAD/.pixi/envs/default/Library/bin/FreeCADCmd.exe  --script G:/FreeCAD/IntegrationTests/Scripts/EvaluateFile.FCMacro --fcstd-dir G:/FreeCAD/IntegrationTests/Data/CADFiles/ --baseline-dir G:/FreeCAD/IntegrationTests/Data/BaselineResults/  --exceptions-dir G:/FreeCAD/IntegrationTests/Data/Exceptions/ --known-failures-dir G:/FreeCAD/IntegrationTests/Data/KnownFailures/
```

```
python Scripts/RunIntegrationTests.py \
  --freecad /path/to/FreeCADCmd \
  --script Scripts/EvaluateFile.FCMacro \
  --fcstd-dir Data/CADFiles/ \
  --baseline-dir Data/BaselineResults/ \
  [options]
```

| Argument               | Default      | Description                                                  |
|------------------------|--------------|--------------------------------------------------------------|
| `--freecad`            | *(required)* | Path to FreeCADCmd executable                                |
| `--script`             | *(required)* | Path to the evaluation macro                                 |
| `--fcstd-dir`          | *(required)* | Folder containing `.FCStd` files                             |
| `--baseline-dir`       | *(required)* | Folder containing baseline JSON files                        |
| `--match-percentage`   | 99.99        | Required match percentage (99.99 = 0.01% relative tolerance) |
| `--absolute-tolerance` | 1e-6         | Absolute tolerance floor for near-zero comparisons           |
| `--bbox-tolerance-mm`  | 1.0          | Absolute tolerance in mm for bounding box and center of mass |
| `--recursive`          | off          | Recurse into subfolders of `--fcstd-dir`                     |
| `--timeout`            | 300          | Per-file FreeCAD timeout in seconds                          |
| `--verbose`            | off          | Print per-file diffs (otherwise only summary and failures)   |
| `--filename`           | *(none)*     | Test a single `.FCStd` file by name                          |
| `--exceptions-dir`     | *(none)*     | Folder with accepted-change exception JSON files             |
| `--known-failures-dir` | *(none)*     | Folder with known-failure rule JSON files                    |
| `--strict`             | off          | Ignore all exceptions and known failures                     |

**Exit codes:** 0 = all pass, 2 = mismatches found, 3 = errors (crashes, missing files, bad JSON).

---

### TestPR.py

Tests a FreeCAD pull request end-to-end: fetches the PR branch into a git worktree, builds with pixi, and runs the integration test suite against the result. Requires the `gh` CLI and pixi. On Windows also requires MSVC.

```
python Scripts/TestPR.py <pr_number> [options]
```

| Argument       | Default                  | Description                               |
|----------------|--------------------------|-------------------------------------------|
| `pr_number`    | *(required, positional)* | GitHub PR number (from FreeCAD/FreeCAD)   |
| `--config`     | release                  | Build configuration: `release` or `debug` |
| `--skip-build` | off                      | Reuse existing build in the worktree      |
| `--filename`   | *(none)*                 | Test only a single `.FCStd` file          |
| `--strict`     | off                      | Ignore all exceptions and known failures  |
| `--cleanup`    | off                      | Remove the worktree after testing         |

**Exit codes:** 0 = all pass, 2 = mismatches, 3 = errors.

Worktrees are created under `G:/FreeCAD/FreeCAD/worktrees/pr-<number>`.

---

### AddTestCase.py

Interactive helper for adding a new `.FCStd` file to the test suite. Walks the user through metadata inspection, license validation, file naming, baseline generation, and a verification test run.

```
python Scripts/AddTestCase.py <path/to/file.FCStd> [--freecad /path/to/FreeCADCmd]
```

| Argument    | Default                  | Description                                              |
|-------------|--------------------------|----------------------------------------------------------|
| `fcstd`     | *(required, positional)* | Path to the source `.FCStd` file                         |
| `--freecad` | *(none)*                 | Path to FreeCADCmd (for baseline generation and testing) |

**Exit codes:** 0 = success, 1 = failure or user cancelled.

The script prompts interactively for metadata (author, license, comment) and offers a list of compatible open-source licenses. It copies the file into `Data/CADFiles/`, generates a baseline, and runs a test to confirm it passes.

---

### CheckFCStdForSuitability.py

Checks whether a single `.FCStd` file is suitable for the integration test suite. Extracts metadata (version, license, author), then runs `EvaluateFile.FCMacro` twice: once with the FreeCAD version that created the file, and once with the latest dev build via pixi. Reports one of three outcomes:

- **REJECTED** -- the file fails in its native FreeCAD version (invalid solids, unsolved sketches, bad license, etc.) and is not suitable for the test suite.
- **ACCEPTED** -- both native and dev builds produce clean results.
- **REGRESSION** -- clean in the native version but broken in dev, indicating a FreeCAD regression worth investigating.

```
python Scripts/CheckFCStdForSuitability.py <path/to/file.FCStd> [options]
```

| Argument     | Default | Description                                              |
|--------------|---------|----------------------------------------------------------|
| `fcstd`      | *(required, positional)* | Path to the `.FCStd` file to check      |
| `--skip-dev` | off     | Skip the dev build evaluation (native only)              |
| `--timeout`  | 300     | Per-evaluation FreeCAD timeout in seconds                |

**Exit codes:** 0 = ACCEPTED, 1 = REJECTED, 2 = REGRESSION, 3 = error.

---

### AnalyzeLibrary.py

Scans a directory tree of `.FCStd` files, extracts metadata (version, license, author, size), evaluates each with its matching FreeCAD version, and records test suitability to a JSON analysis file.

```
python Scripts/AnalyzeLibrary.py <directory> [options]
```

| Argument       | Default                  | Description                                              |
|----------------|--------------------------|----------------------------------------------------------|
| `directory`    | *(required, positional)* | Root directory to scan                                   |
| `--output`, `-o` | library_analysis.json  | Output JSON file                                         |
| `--max-size`   | 5.0                      | Only evaluate files smaller than this (MB)               |
| `--timeout`    | 60                       | Per-file FreeCAD timeout in seconds                      |
| `--resume`     | off                      | Resume from existing output, skipping already-analyzed files |
| `--workers`    | 8                        | Number of parallel FreeCAD evaluations                   |

Uses `ThreadPoolExecutor` for parallel evaluation. Saves progress periodically (every 50 files) so interrupted runs can be resumed with `--resume`.

---

### CheckLicenses.py

Validates license metadata for all `.FCStd` files in the test suite. Checks that each file has a compatible open-source license, an author, a source comment, an entry in `THIRD_PARTY_CREDITS.md`, and a corresponding license text in `LICENSES/`.

```
python Scripts/CheckLicenses.py [options]
```

| Argument         | Default                | Description                          |
|------------------|------------------------|--------------------------------------|
| `--fcstd-dir`    | Data/CADFiles          | Directory containing test files      |
| `--credits`      | THIRD_PARTY_CREDITS.md | Path to credits file                 |
| `--licenses-dir` | LICENSES               | Directory containing license text files |

**Exit codes:** 0 = all checks pass, 1 = problems found.

---

### TestLibraryVersions.py

Tests library files across multiple FreeCAD versions to record version compatibility. For each pre-0.21 test-suitable file in `library_analysis.json`, it baselines with FreeCAD 0.21 and compares against 1.0 and the dev build.

```
python Scripts/TestLibraryVersions.py [options]
```

| Argument          | Default              | Description                                          |
|-------------------|----------------------|------------------------------------------------------|
| `--analysis`      | *(hardcoded path)*   | Path to `library_analysis.json`                      |
| `--versions`      | 0.21 1.0 dev         | FreeCAD versions to test                             |
| `--timeout`       | 120                  | Per-file per-version timeout in seconds              |
| `--workers`       | 1                    | Number of parallel file evaluations                  |
| `--resume`        | off                  | Skip files that already have `version_tests` results |
| `--save-interval` | 25                   | Save after every N files                             |
| `--limit`         | 0                    | Stop after N files (0 = no limit)                    |

Results are written back into `library_analysis.json` under a `version_tests` key.

---

## FreeCAD Macros

### EvaluateFile.FCMacro

The core evaluation macro (Python 3, FreeCAD >= 0.18). Opens an `.FCStd` file, forces a full touch-recompute, identifies final solid objects via the dependency graph, runs all analyzers, and writes a schema v4 JSON report.

**Invocation via command-line arguments** (precompiled release binaries, non-pixi local builds):

```
FreeCADCmd Scripts/EvaluateFile.FCMacro input.FCStd --out report.json
```

**Invocation via environment variables** (required for pixi builds):

When FreeCADCmd is launched via pixi, it consumes positional file arguments (`.FCStd`, `.FCMacro`) itself rather than passing them through to the macro's `sys.argv`. Use environment variables instead:

```
cd G:/FreeCAD/FreeCAD && eval "$(pixi shell-hook)" && \
  EVALUATE_FCSTD="/path/to/file.FCStd" \
  EVALUATE_OUT="/path/to/report.json" \
  FreeCADCmd /path/to/EvaluateFile.FCMacro
```

| Argument / Variable          | Description                              |
|------------------------------|------------------------------------------|
| `fcstd` / `EVALUATE_FCSTD`  | Path to the `.FCStd` file                |
| `--out` / `EVALUATE_OUT`    | Output file path (defaults to stdout)    |

The macro checks for environment variables first. If `EVALUATE_FCSTD` is set, it takes precedence over any positional arguments.

**Analyzers:** solids, sketches, partdesign_bodies, partdesign_features, part_features, app_parts, assemblies, techdraw_pages, spreadsheets, links, part_extrusions, materials.

### EvaluateFilePy2.FCMacro

Python 2 compatible version for FreeCAD 0.14--0.17. Produces the same schema v4 JSON output but avoids type annotations, f-strings, and APIs added after 0.17. Does not support the environment variable invocation method.

```
FreeCADCmd Scripts/EvaluateFilePy2.FCMacro input.FCStd --out report.json
```

---

## Library Modules

These are not invoked directly -- they provide shared types and utilities used by the executable scripts.

### freecad_binaries.py

Single source of truth for FreeCAD binary paths, version parsing, and macro selection. All scripts that need to locate a FreeCADCmd executable import from here. Provides `PORTABLE_BINARIES` (version tuple to path mapping), `FREECAD_PIXI_DIR`, `PY2_VERSIONS`, `parse_version()`, `needs_py2()`, `macro_for_version()`, and `resolve_freecad()` (which tries exact match, then archived 7z extraction, then closest version fallback).

### metric_types.py

Shared dataclasses for the metric extraction and comparison pipeline: `MetricKey`, `CompareConfig`, `MetricDiff`, and the `make_simple_extractor` factory function used by all report sections.

### extractors/\_\_init\_\_.py

Registry of `(section_name, extractor_function)` pairs. All sections use `make_simple_extractor` from `metric_types.py`. Sections: solids, sketches, partdesign_bodies, partdesign_features, part_features, app_parts, assemblies, techdraw_pages, spreadsheets, links, part_extrusions, materials.

### accepted_changes.py

Loads and matches exception rules that downgrade known cross-version differences from failures to accepted changes. Rules are stored as JSON in `Data/Exceptions/` (`_global.json` for all files, `<stem>.json` for specific files). Patterns use fnmatch wildcards.

### license_utils.py

License string recognition and validation. Maps free-form license strings to SPDX identifiers via exact alias lookup and regex matching. Checks for incompatible licenses (NonCommercial, NoDerivatives). Used by `CheckLicenses.py` and `AddTestCase.py`.
