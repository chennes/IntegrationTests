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
| `--recursive`          | **on**       | Recurse into subfolders of `--fcstd-dir` (so bundle subdirs are found). Use `--no-recursive` for a flat scan. |
| `--timeout`            | 300          | Per-file FreeCAD timeout in seconds                          |
| `--verbose`            | off          | Print per-file diffs (otherwise only summary and failures)   |
| `--filename`           | *(none)*     | Test a single `.FCStd` file by name                          |
| `--exceptions-dir`     | *(none)*     | Folder with accepted-change exception JSON files             |
| `--known-failures-dir` | *(none)*     | Folder with known-failure rule JSON files                    |
| `--strict`             | off          | Ignore all exceptions and known failures                     |

**Exit codes:** 0 = all pass, 2 = mismatches found, 3 = errors (crashes, missing files, bad JSON).

**Multi-file bundles.** A test case is normally a single self-contained `.FCStd` directly in `--fcstd-dir`. For models with cross-document dependencies -- e.g. an external VarSet in one file driving geometry in others, or assemblies that link sibling parts -- put the interdependent files together in a **subdirectory** of `--fcstd-dir` (recursion is on by default, so the bundle is discovered). Because the harness opens each file in place, FreeCAD resolves co-located dependencies automatically. Two rules apply to bundles:

- **Baselines mirror the relative path.** `CADFiles/<bundle>/<name>.FCStd` is compared against `BaselineResults/<bundle>/<name>.json`, so bundle members never collide with each other or with flat files on a bare stem. (Flat files are unchanged: `Pincher.FCStd` -> `Pincher.json`.)
- **Dependency-only files go in `_deps.txt`.** A file whose name is listed in a `_deps.txt` in the same bundle directory is kept on disk (so co-located references resolve) but is **not** itself a test target -- it needs no baseline and its own validity is not graded. Use this for parameter/driver documents (e.g. a VarSet master) or any dependency that is not a final-geometry file.

Keep the original filenames inside a bundle: cross-document references resolve by FreeCAD document name (derived from the filename at save time), so renaming a dependency would break resolution.

Example: `Data/CADFiles/ServoQuetsch/` holds 6 parts plus `V.FCStd` (the VarSet master, listed in `_deps.txt`); the parts are driven by `V#VarSet.<param>` expressions.

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

## Inventory Pipeline

The scripts below build a unified picture of every `.FCStd` file we have available locally for test-suite consideration -- not just those already in the suite. The data flow is:

```
BuildInventory.py         -> Data/Inventory.json + Data/Inventory.md
EvaluateNativeAndRelease.py -> Data/EvaluationMatrix.json
AnalyzeSuiteSuitability.py  -> Data/SuiteSuitabilityMatrix.json
```

Each step is independent and resume-safe. `BuildInventory.py` reads the other two files when present and merges their results into the inventory.

### BuildInventory.py

Walks one or more source-collection roots, extracts metadata from each `.FCStd` file's `Document.xml`, and writes a unified inventory. Handles both ordinary ZIP-archive `.FCStd` files and zippey-decoded plaintext (the `freecad-models` repo uses the latter on checkout). Optionally enriches each entry with evaluation results from `AnalyzeLibrary.py` outputs and the native/release evaluation matrix.

```
python Scripts/BuildInventory.py --root path[=name] [--root path[=name] ...] [options]
```

| Argument         | Default                            | Description                                                  |
|------------------|------------------------------------|--------------------------------------------------------------|
| `--root`         | *(at least one required)*          | A source-collection root. Use `path=name` to set an explicit collection name; otherwise the directory's basename is used. |
| `--merge`        | *(none)*                           | An `AnalyzeLibrary.py` output JSON to merge solid counts/test-suitability from. Repeatable. |
| `--eval-matrix`  | `Data/EvaluationMatrix.json`       | Path to the native+release evaluation matrix. If present, `native_pass`/`release_pass` are added to each entry. |
| `--output`, `-o` | `Data/Inventory.json`              | Output JSON inventory                                        |
| `--md`           | `Data/Inventory.md`                | Markdown summary (per-collection counts, license buckets, version distribution, recompute results) |

Each inventory entry records the source collection, absolute and relative paths, file size, FreeCAD version that wrote it, license, author, comment, object count, draft modules, python proxy modules, and any merged evaluation data.

---

### EvaluateNativeAndRelease.py

For every file in `Data/Inventory.json`, runs `EvaluateFile.FCMacro` against (a) the FreeCAD version that wrote the file ("native") and (b) the latest stable release pinned in `freecad_binaries.LATEST_RELEASE_EXE`. Writes per-file pass/fail and solid counts to `Data/EvaluationMatrix.json`.

Always uses environment-variable invocation so non-ASCII paths and Windows ANSI argv quirks do not break the evaluation. Resume-safe: existing matrix entries are skipped, and partial results are saved every N files.

```
python Scripts/EvaluateNativeAndRelease.py [options]
```

| Argument          | Default                          | Description                                              |
|-------------------|----------------------------------|----------------------------------------------------------|
| `--inventory`     | `Data/Inventory.json`            | Source inventory                                         |
| `--output`        | `Data/EvaluationMatrix.json`     | Where to write per-file results                          |
| `--timeout`       | 90                               | Per-evaluation FreeCAD timeout in seconds                |
| `--workers`       | 8                                | Parallel evaluation workers                              |
| `--max-size-mb`   | 20                               | Skip files larger than this (recorded as `skipped`)      |
| `--collections`   | *(none)*                         | Restrict to specific collection names                    |
| `--limit`         | *(none)*                         | Cap fresh evaluations (smoke-testing)                    |
| `--reuse-native`  | *(none)*                         | An `AnalyzeLibrary.py` output to reuse native results from |
| `--no-native`     | off                              | Skip native evaluation (release only)                    |
| `--no-release`    | off                              | Skip release evaluation (native only)                    |
| `--save-every`    | 25                               | Save partial output every N files                        |

The release binary path comes from `freecad_binaries.LATEST_RELEASE_EXE` -- update that constant when a newer release is published.

---

### AnalyzeSuiteSuitability.py

For every inventory file that already passes recompute in 1.1.1, runs `EvaluateFile.FCMacro` against 1.1.1 **twice** in independent FreeCAD subprocesses with separate user-config dirs, then compares the two reports section-by-section using the same `compare_maps` logic the test suite itself uses. Any non-zero diff means the file is non-deterministic under recompute and is unsuitable as a baseline-vs-rerun test case.

Also classifies every reported object into a workbench bucket (PartDesign / Part / Sketcher / Assembly / TechDraw / Spreadsheet / Material / FEM / Path / etc.) and builds a per-file feature index covering object-type counts, addons detected (Draft / Arch / BIM / A2plus / FastenersWB / ThreadProfile / Path), and presence flags (`has_assembly`, `has_techdraw`, `has_spreadsheet`, ...).

```
python Scripts/AnalyzeSuiteSuitability.py [options]
```

| Argument          | Default                                | Description                                              |
|-------------------|----------------------------------------|----------------------------------------------------------|
| `--inventory`     | `Data/Inventory.json`                  | Source inventory                                         |
| `--eval-matrix`   | `Data/EvaluationMatrix.json`           | Used to filter to files that pass release recompute      |
| `--output`        | `Data/SuiteSuitabilityMatrix.json`     | Where to write per-file analysis                         |
| `--file`          | *(none)*                               | Single-file diagnostic mode (skips inventory, prints JSON) |
| `--collections`   | *(none)*                               | Restrict to specific collection names                    |
| `--max-size-mb`   | 50                                     | Skip files larger than this                              |
| `--workers`       | 8                                      | Parallel analysis workers (uses `ProcessPoolExecutor`)   |
| `--timeout`       | 300                                    | Per-FreeCAD-run timeout in seconds                       |
| `--limit`         | *(none)*                               | Cap fresh analyses                                       |
| `--save-every`    | 25                                     | Save partial output every N files                        |

The `would_pass_suite` field in each entry is the headline answer: `true` only if the file is deterministic, has at least one comparable section, and has zero invalid solids. The `feature_index` and `workbench_counts` fields support queries like "all PartDesign+Spreadsheet files in the parts library that use no addons and would pass cleanly."

Files in `Data/SlowFiles.md` (extreme recompute time, e.g. KiCAD-derived PCBs) are always skipped via a hardcoded list in the script.

---

## Utilities

### UnzippeyFCStd.py

Converts zippey-decoded `.FCStd` files back into real `.FCStd` ZIP archives. The `freecad-models` repo (and others) use the [zippey](https://github.com/sippey/zippey) git filter, which decodes the FCStd zip into plaintext at checkout for diff-friendliness. The on-disk layout is a sequence of entries, each starting with a header line `<stored_size>|<original_size>|<A|B>|<filename>` followed by the raw or base64-encoded content. This script reverses that.

```
python Scripts/UnzippeyFCStd.py <src> <dst> [options]
```

| Argument         | Default                | Description                                             |
|------------------|------------------------|---------------------------------------------------------|
| `src`            | *(required)*           | Single zippey-decoded `.FCStd` file or a directory      |
| `dst`            | *(required)*           | Output `.FCStd` file (single-file mode) or directory    |
| `--recursive`    | off                    | Recurse into directories looking for `*.FCStd`          |
| `--only-zippey`  | off                    | When scanning a directory, skip files that are already real ZIPs |

Handles Windows CRLF expansion that occurs at checkout, and base64-decodes binary entries. The output `.FCStd` always places `Document.xml` first by convention; everything else preserves the original entry order and uses deflate compression.

---

### ScanForViewProviderOrigin.py

Walks a directory tree of `.FCStd` files and reports any file whose `Document.xml` references the legacy `Gui::ViewProviderOrigin` class as an exact-name match. Used to find files that need FreeCAD PR #29608 (`Gui: Re-add ViewProviderOrigin`) to load correctly.

```
python Scripts/ScanForViewProviderOrigin.py <root> [--workers N]
```

| Argument    | Default      | Description                                  |
|-------------|--------------|----------------------------------------------|
| `root`      | *(required)* | Directory to scan recursively                |
| `--workers` | 8            | Parallel scan workers                        |

The match requires a non-identifier character after the class name so it does not falsely match the longer `Gui::ViewProviderOriginGroupExtension` class.

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

The `part_features` analyzer records `is_valid`, `shape_type`, `shell_is_closed`,
`placement_base`, `bounding_box`, `total_area_mm2`, `total_volume_mm3`, and
`center_of_mass`. The geometric metrics (added 2026-05) let the suite catch
regressions where a Part::Feature's visible position is unchanged across
versions but its internal coordinates and Placement diverge -- the class of
bug behind FreeCAD issue #29733 (`transformShape()` no longer bakes the
transform in 1.2-dev). When extending or regenerating baselines, ensure the
target FreeCAD version is the same one that wrote each FCStd file.

### EvaluateFilePy2.FCMacro

Python 2 compatible version for FreeCAD 0.14--0.17. Produces the same schema v4 JSON output but avoids type annotations, f-strings, and APIs added after 0.17. Supports both command-line and environment-variable invocation modes, identical to `EvaluateFile.FCMacro`. Env-var mode is the safer choice on Windows because `FreeCADCmd` mangles `argv` containing UTF-8 paths plus spaces.

```
# Command-line mode
FreeCADCmd Scripts/EvaluateFilePy2.FCMacro input.FCStd --out report.json

# Env-var mode (preferred on Windows for non-ASCII paths)
EVALUATE_FCSTD=input.FCStd EVALUATE_OUT=report.json \
  FreeCADCmd Scripts/EvaluateFilePy2.FCMacro
```

---

## Library Modules

These are not invoked directly -- they provide shared types and utilities used by the executable scripts.

### freecad_binaries.py

Single source of truth for FreeCAD binary paths, version parsing, and macro selection. All scripts that need to locate a FreeCADCmd executable import from here. Provides:

- `PORTABLE_BINARIES` -- version tuple `(major, minor)` to FreeCADCmd path mapping (0.13 through 1.1).
- `FREECAD_PIXI_DIR` -- pixi dev build location.
- `LATEST_RELEASE_VERSION` and `LATEST_RELEASE_EXE` -- the latest stable release used by `EvaluateNativeAndRelease.py`. Update both when a newer release is published.
- `PY2_VERSIONS` -- the set of versions that ship Python 2 and require `EvaluateFilePy2.FCMacro`.
- Helpers: `parse_version()`, `needs_py2()`, `macro_for_version()`, `resolve_freecad()` (tries exact match, then closest version fallback, then most-recent weekly extracted on demand via 7-Zip).

### metric_types.py

Shared dataclasses for the metric extraction and comparison pipeline: `MetricKey`, `CompareConfig`, `MetricDiff`, and the `make_simple_extractor` factory function used by all report sections.

### extractors/\_\_init\_\_.py

Registry of `(section_name, extractor_function)` pairs. All sections use `make_simple_extractor` from `metric_types.py`. Sections: solids, sketches, partdesign_bodies, partdesign_features, part_features, app_parts, assemblies, techdraw_pages, spreadsheets, links, part_extrusions, materials.

### accepted_changes.py

Loads and matches exception rules that downgrade known cross-version differences from failures to accepted changes. Rules are stored as JSON in `Data/Exceptions/` (`_global.json` for all files, `<stem>.json` for specific files). Patterns use fnmatch wildcards.

### license_utils.py

License string recognition and validation. Maps free-form license strings to SPDX identifiers via exact alias lookup and regex matching. Checks for incompatible licenses (NonCommercial, NoDerivatives). Used by `CheckLicenses.py` and `AddTestCase.py`.
