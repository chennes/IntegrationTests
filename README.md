[![Integration Test Suite](https://github.com/chennes/IntegrationTests/actions/workflows/run_integration_tests.yml/badge.svg)](https://github.com/chennes/IntegrationTests/actions/workflows/run_integration_tests.yml)

# FreeCAD Integration Test Suite

A collection of FreeCAD files with known baseline results that can be automatically tested against a local copy of FreeCAD to evaluate it. Runs via a GitHub action once per day to evaluate https://github.com/FreeCAD/FreeCAD (main branch only).

## Running manually

For example (replacing the path to the FreeCAD executable with a real path):
```
 ./Scripts/RunIntegrationTests.py --freecad /path/to/bin/FreeCADCmd --script Scripts/EvaluateFile.FCMacro --fcstd-dir Data/CADFiles/ --baseline-dir Data/BaselineResults/ --verbose
 ```

## To add a new test case

### Licensing requirements

Every FCStd file in this repository must have a compatible open-source license. Before adding a file, verify that:

1. The file's **in-file metadata** (File > Project Information in FreeCAD) has `License` and `LicenseURL` set to an open-source license. Accepted licenses include CC-BY, CC-BY-SA, LGPL, CERN OHL, Public Domain, and similar. NonCommercial (NC) licenses are not accepted.
2. The `CreatedBy` field identifies the author.
3. The `Comment` field identifies the source project and URL (if the file is from an external project).

If the file's license requires that the license text be included, verify that the full text is present in the `LICENSES/` directory.

### Naming conventions

- Files created for this test suite: use a workbench prefix, e.g. `PD_MyPart.FCStd` (PartDesign), `Part_MyPart.FCStd`, `Sketcher_MyPart.FCStd`.
- Files from external projects: use a source prefix, e.g. `FL_PartName.FCStd` (FreeCAD-Library by episource), `MG_PartName.FCStd` (mgesteiro), `STEMFIE_PartName.FCStd`, `OBJ_PartName.FCStd` (Obijuan). When adding files from a new project, choose a short, unique prefix.

### Steps

1. Save the FCStd file in `Data/CADFiles/` using the naming convention above.
2. Set the file's metadata (CreatedBy, License, LicenseURL, Comment) if not already set.
3. Generate a baseline using a known-good version of FreeCAD:
```
FreeCADCmd.exe Scripts/EvaluateFile.FCMacro Data/CADFiles/SomeDescriptiveName.FCStd --out Data/BaselineResults/SomeDescriptiveName.json
```
4. Run the test suite to confirm the new file passes:
```
python Scripts/RunIntegrationTests.py --freecad /path/to/FreeCADCmd --script Scripts/EvaluateFile.FCMacro --fcstd-dir Data/CADFiles/ --baseline-dir Data/BaselineResults/ --exceptions-dir Data/Exceptions/ --filename SomeDescriptiveName.FCStd --verbose
```
5. Add the file to `Tests.md`.
6. Add attribution to `THIRD_PARTY_CREDITS.md` (for third-party files) or add the file to the appropriate "Original Files" section.
7. Create a PR to this repository with the new files and updated documentation.

### Known/expected changes (exceptions)

When a FreeCAD version change intentionally alters geometry (e.g. OCC kernel updates changing edge counts, shape type changes from Solid to Compound), add an exception rule rather than treating it as a test failure. Exception rules live in `Data/Exceptions/` as JSON files:

- `_global.json` -- rules that apply to all test files.
- `<stem>.json` -- rules that apply only to a specific FCStd file.

See `Scripts/accepted_changes.py` for the rule format and matching logic. Pass `--exceptions-dir Data/Exceptions/` when running tests to enable them.
