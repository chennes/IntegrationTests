# FreeCAD Integration Test Suite

A collection of FreeCAD files with known baseline results that can be automatically tested against a local copy of FreeCAD to evaluate it.

## Running manually

For example (replacing the path to the FreeCAD executable with a real path):
```
 ./Scripts/RunIntegrationTests.py --freecad /path/to/bin/FreeCADCmd --script Scripts/EvaluateFile.FCMacro --fcstd-dir Data/CADFiles/ --baseline-dir Data/BaselineResults/ --verbose
 ```

## To add a new test case

1. Save the FCStd file in the Data/CADFiles directory
2. Using a known-good version of FreeCAD, run
```
FreeCADCmd.exe Scripts/EvaluateFile.FCMacro Data/SomeDescriptiveName.FCStd --out SomeDescriptiveName.json 
```
3. Store the resulting `SomeDescriptiveName.json` file in Data/BaselineResults
4. Add test information to Tests.md
5. Create a PR to this repository with the new files and updated documentation.
