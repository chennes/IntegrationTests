#!/usr/bin/env python3
"""Interactive helper for adding a new FCStd file to the integration test suite.

Takes an FCStd file as input and walks the user through:
  1. Inspecting and fixing in-file metadata (author, license, comment)
  2. Choosing a test filename following naming conventions
  3. Copying the file into Data/CADFiles/
  4. Generating a baseline with FreeCAD
  5. Verifying the license text exists in LICENSES/
  6. Checking THIRD_PARTY_CREDITS.md
  7. Running the test to confirm it passes

Usage:
  python Scripts/AddTestCase.py path/to/model.FCStd
  python Scripts/AddTestCase.py path/to/model.FCStd --freecad /path/to/FreeCADCmd
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from defusedxml.ElementTree import fromstring as parse_xml  # noqa: E402
from license_utils import (  # noqa: E402
    normalize_license,
    is_incompatible,
    is_placeholder,
    get_license_info,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CAD_DIR = PROJECT_ROOT / "Data" / "CADFiles"
BASELINE_DIR = PROJECT_ROOT / "Data" / "BaselineResults"
EXCEPTIONS_DIR = PROJECT_ROOT / "Data" / "Exceptions"
LICENSES_DIR = PROJECT_ROOT / "LICENSES"
CREDITS_PATH = PROJECT_ROOT / "THIRD_PARTY_CREDITS.md"
MACRO_PATH = SCRIPT_DIR / "EvaluateFile.FCMacro"
TEST_RUNNER = SCRIPT_DIR / "RunIntegrationTests.py"


def prompt(message: str, default: str = "") -> str:
    """Prompt the user for input with an optional default.

    Args:
        message: The prompt message.
        default: Default value shown in brackets. If the user presses Enter
            without typing anything, this value is returned.

    Returns:
        The user's input, or the default if they entered nothing.
    """
    if default:
        result = input(f"{message} [{default}]: ").strip()
        return result if result else default
    return input(f"{message}: ").strip()


def prompt_yes_no(message: str, default: bool = True) -> bool:
    """Prompt the user for a yes/no answer.

    Args:
        message: The prompt message.
        default: Default answer if the user presses Enter.

    Returns:
        True for yes, False for no.
    """
    suffix = " [Y/n]: " if default else " [y/N]: "
    result = input(message + suffix).strip().lower()
    if not result:
        return default
    return result in ("y", "yes")


def extract_metadata(path: Path) -> Dict[str, str]:
    """Extract document properties from an FCStd file.

    Args:
        path: Path to the FCStd file.

    Returns:
        A dict mapping property names to their string values.
    """
    metadata: Dict[str, str] = {}
    try:
        with zipfile.ZipFile(path, "r") as z:
            if "Document.xml" not in z.namelist():
                return metadata
            with z.open("Document.xml") as dx:
                root = parse_xml(dx.read())

        # ProgramVersion is an attribute on the root Document element
        pv = root.get("ProgramVersion", "")
        if pv:
            metadata["ProgramVersion"] = pv

        for prop_el in root.iter("Property"):
            pname = prop_el.get("name", "")
            if pname in (
                "CreatedBy",
                "License",
                "LicenseURL",
                "Comment",
                "Company",
                "CreationDate",
                "LastModifiedBy",
                "LastModifiedDate",
            ):
                for s in prop_el.iter("String"):
                    val = s.get("value", "")
                    if val and pname not in metadata:
                        metadata[pname] = val
                    elif pname not in metadata:
                        metadata[pname] = ""
                    break
    except Exception as e:
        print(f"  Warning: could not read metadata: {e}")
    return metadata


def update_metadata(path: Path, updates: Dict[str, str]) -> None:
    """Write updated document properties into an FCStd file.

    Handles three cases per requested update:
      1. The Property element and its String child both exist -> overwrite the value.
      2. The Property element exists but has no String child -> insert one.
      3. No Property element exists -> append a new
         `<Property name="X" type="App::PropertyString"><String value="..."/></Property>`
         inside `<Properties>` and bump its `Count` attribute.

    Args:
        path: Path to the FCStd file (modified in-place).
        updates: Dict of property names to new values.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=".FCStd") as tmp:
        tmp_path = tmp.name

    with zipfile.ZipFile(path, "r") as zin, zipfile.ZipFile(tmp_path, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Document.xml":
                root = ET.fromstring(data)
                _apply_property_updates(root, updates)
                data = ET.tostring(root, encoding="unicode").encode("utf-8")
            zout.writestr(item, data)

    shutil.move(tmp_path, str(path))


def _apply_property_updates(root: ET.Element, updates: Dict[str, str]) -> None:
    """Apply property-name -> value updates to a Document.xml ElementTree root.

    Inserts missing String children or whole Property elements as needed so
    files with old/incomplete property tables get a complete metadata block.
    """
    existing: Dict[str, ET.Element] = {}
    for prop_el in root.iter("Property"):
        name = prop_el.get("name", "")
        if name and name not in existing:
            existing[name] = prop_el

    properties_container: Optional[ET.Element] = None
    added_count = 0

    for pname, value in updates.items():
        prop_el = existing.get(pname)
        if prop_el is not None:
            string_child = next(iter(prop_el.iter("String")), None)
            if string_child is not None:
                string_child.set("value", value)
            else:
                ET.SubElement(prop_el, "String", {"value": value})
            continue

        if properties_container is None:
            properties_container = root.find("Properties")
            if properties_container is None:
                properties_container = ET.SubElement(root, "Properties", {"Count": "0"})
        new_prop = ET.SubElement(
            properties_container,
            "Property",
            {"name": pname, "type": "App::PropertyString"},
        )
        ET.SubElement(new_prop, "String", {"value": value})
        existing[pname] = new_prop
        added_count += 1

    if added_count and properties_container is not None:
        try:
            current_count = int(properties_container.get("Count", "0"))
        except ValueError:
            current_count = sum(1 for _ in properties_container.iter("Property"))
        properties_container.set("Count", str(current_count + added_count))


def step_inspect_metadata(source_path: Path) -> Dict[str, str]:
    """Display current metadata and return it.

    Args:
        source_path: Path to the FCStd file.

    Returns:
        The extracted metadata dict.
    """
    print("\n--- Step 1: Inspect file metadata ---\n")
    metadata = extract_metadata(source_path)

    pv = metadata.get("ProgramVersion", "unknown")
    print(f"  Created with FreeCAD: {pv}")
    print()

    fields = ["CreatedBy", "License", "LicenseURL", "Comment", "Company"]
    for field in fields:
        val = metadata.get(field, "(not present)")
        if not val:
            val = "(empty)"
        print(f"  {field}: {val}")

    return metadata


def step_fix_metadata(source_path: Path, metadata: Dict[str, str]) -> Dict[str, str]:
    """Interactively fix missing or placeholder metadata.

    Args:
        source_path: Path to the FCStd file (will be modified if needed).
        metadata: Current metadata dict.

    Returns:
        The updated metadata dict.
    """
    print("\n--- Step 2: Fix metadata ---\n")
    updates: Dict[str, str] = {}

    # CreatedBy
    if not metadata.get("CreatedBy"):
        print("  The file has no author set.")
        author = prompt("  Enter the author's name (e.g. 'Jane Doe')")
        if author:
            updates["CreatedBy"] = author
    else:
        print(f"  Author: {metadata['CreatedBy']}")

    # License
    license_str = metadata.get("License", "")
    if is_placeholder(license_str):
        if license_str.lower().strip() == "all rights reserved":
            print("\n  The file says 'All rights reserved' -- this is FreeCAD's default")
            print("  and usually means the author didn't set a license.")
        else:
            print("\n  The file has no license set.")

        print("\n  Recommended licenses for open-source hardware:")
        print("    1. CERN OHL v2 -- Strongly Reciprocal (CERN-OHL-S-2.0)")
        print("    2. CERN OHL v2 -- Weakly Reciprocal (CERN-OHL-W-2.0)")
        print("    3. CERN OHL v2 -- Permissive (CERN-OHL-P-2.0)")
        print("    4. Creative Commons Attribution 4.0 (CC-BY-4.0)")
        print("    5. Creative Commons Attribution-ShareAlike 4.0 (CC-BY-SA-4.0)")
        print("    6. Creative Commons Zero 1.0 (CC0-1.0)")
        print("    7. Other (enter manually)")
        print("    0. Cancel -- cannot add file without a license")

        choice = prompt("\n  Choose a license (0-7)", "1")
        license_map = {
            "1": (
                "CERN Open Hardware Licence Version 2 - Strongly Reciprocal",
                "https://ohwr.org/cernohl",
            ),
            "2": (
                "CERN Open Hardware Licence Version 2 - Weakly Reciprocal",
                "https://ohwr.org/cernohl",
            ),
            "3": (
                "CERN Open Hardware Licence Version 2 - Permissive",
                "https://ohwr.org/cernohl",
            ),
            "4": (
                "Creative Commons Attribution 4.0",
                "https://creativecommons.org/licenses/by/4.0/",
            ),
            "5": (
                "Creative Commons Attribution-ShareAlike 4.0",
                "https://creativecommons.org/licenses/by-sa/4.0/",
            ),
            "6": (
                "Creative Commons Zero 1.0 Universal",
                "https://creativecommons.org/publicdomain/zero/1.0/",
            ),
        }

        if choice == "0":
            print("\n  Cannot add a file without a compatible license. Aborting.")
            sys.exit(1)
        elif choice in license_map:
            lic_name, lic_url = license_map[choice]
            updates["License"] = lic_name
            updates["LicenseURL"] = lic_url
            print(f"  -> {lic_name}")
        elif choice == "7":
            lic_name = prompt("  License name")
            lic_url = prompt("  License URL")
            if not lic_name:
                print("  Cannot add a file without a license. Aborting.")
                sys.exit(1)
            updates["License"] = lic_name
            updates["LicenseURL"] = lic_url
        else:
            print("  Invalid choice. Aborting.")
            sys.exit(1)
    elif is_incompatible(license_str):
        print(f"\n  The file's license is '{license_str}', which is not compatible")
        print("  with redistribution in this test suite (NonCommercial clause).")
        print("  You must obtain permission from the author to relicense, or choose")
        print("  a different file. Aborting.")
        sys.exit(1)
    else:
        spdx = normalize_license(license_str)
        if spdx:
            print(f"  License: {license_str} (recognized as {spdx})")
        else:
            print(f"  License: {license_str} (not in known aliases)")
            print("  You may need to add a mapping in Scripts/license_utils.py.")

    # LicenseURL
    if not metadata.get("LicenseURL") and "LicenseURL" not in updates:
        url = prompt("  Enter the license URL")
        if url:
            updates["LicenseURL"] = url

    # Comment (for third-party files)
    if not metadata.get("Comment"):
        print("\n  The file has no Comment field. For third-party files, this should")
        print("  identify the source project and URL.")
        comment = prompt("  Enter a comment (or press Enter to skip)")
        if comment:
            updates["Comment"] = comment

    if updates:
        print("\n  Updating file metadata...")
        update_metadata(source_path, updates)
        metadata.update(updates)
        print("  Done.")
    else:
        print("\n  Metadata looks good, no changes needed.")

    return metadata


def step_choose_filename(source_path: Path) -> str:
    """Help the user choose a filename following naming conventions.

    Args:
        source_path: Path to the original FCStd file.

    Returns:
        The chosen filename (e.g. 'MG_SomePart.FCStd').
    """
    print("\n--- Step 3: Choose test filename ---\n")
    print("  Naming conventions:")
    print("    - Use author/source prefix: MW_, CH_, FPL_, PS_, MG_, JGG_, ...")
    print(f"\n  Original filename: {source_path.name}")

    while True:
        name = prompt("  Enter the test filename (e.g. MW_MyPart.FCStd)")
        if not name:
            continue
        if not name.endswith(".FCStd"):
            name += ".FCStd"
        dest = CAD_DIR / name
        if dest.exists():
            print(f"  '{name}' already exists in Data/CADFiles/. Choose a different name.")
            continue
        return name


def step_copy_file(source_path: Path, dest_name: str) -> Path:
    """Copy the FCStd file into Data/CADFiles/.

    Args:
        source_path: Path to the source FCStd file.
        dest_name: The chosen destination filename.

    Returns:
        The path to the copied file.
    """
    print("\n--- Step 4: Copy file ---\n")
    dest = CAD_DIR / dest_name
    shutil.copy2(str(source_path), str(dest))
    print(f"  Copied to {dest}")
    return dest


def step_check_license_file(metadata: Dict[str, str]) -> None:
    """Check if the license text exists in LICENSES/ and prompt if missing.

    Args:
        metadata: The file's metadata dict.
    """
    print("\n--- Step 5: Check license text ---\n")
    license_str = metadata.get("License", "")
    spdx = normalize_license(license_str)

    if not spdx:
        print(f"  License '{license_str}' not in known aliases -- cannot check automatically.")
        print("  Please verify that the license text is in LICENSES/ manually.")
        return

    if spdx == "PUBLIC-DOMAIN":
        print("  Public Domain -- no license file needed.")
        return

    license_file = LICENSES_DIR / f"{spdx}.txt"
    if license_file.exists():
        print(f"  {license_file.name} already exists. OK.")
    else:
        print(f"  Missing: {license_file}")
        lic_info = get_license_info(spdx)
        if lic_info and lic_info.download_url:
            print(f"  Download from: {lic_info.download_url}")
            print(f"  Save it as: {license_file}")
        else:
            print(f"  Find the full license text for {spdx} and save it as {license_file}")
        input("\n  Press Enter once you have added the license file...")
        if license_file.exists():
            print("  Found. OK.")
        else:
            print(
                f"  Warning: {license_file} still not found. Remember to add it before committing."
            )


def step_generate_baseline(
    dest_path: Path, freecad_exe: Optional[str], metadata: Dict[str, str]
) -> bool:
    """Generate a baseline JSON file using FreeCAD.

    The baseline must be generated with the same FreeCAD version that created
    the file (or the closest available version). This function checks that the
    provided FreeCADCmd matches the file's ProgramVersion.

    Args:
        dest_path: Path to the FCStd file in Data/CADFiles/.
        freecad_exe: Resolved path to FreeCADCmd, or None to skip.
        metadata: File metadata dict (must include ProgramVersion).

    Returns:
        True if the baseline was generated successfully.
    """
    print("\n--- Step 6: Generate baseline ---\n")

    file_version = metadata.get("ProgramVersion", "unknown")
    print(f"  This file was created with FreeCAD {file_version}")
    print(f"  The baseline MUST be generated with the same (or closest) version.")
    print()

    if not freecad_exe:
        stem = dest_path.stem
        print(f"  Skipped (no FreeCADCmd path). Generate the baseline manually")
        print(f"  using FreeCAD {file_version} before committing:")
        print(f"    FreeCADCmd {MACRO_PATH} {dest_path} --out {BASELINE_DIR / (stem + '.json')}")
        return False

    # Verify the FreeCAD version matches
    try:
        ver_proc = subprocess.run(
            [freecad_exe, "--version"], capture_output=True, text=True, timeout=30
        )
        exe_version = ver_proc.stdout.strip().split("\n")[0] if ver_proc.stdout else "unknown"
    except Exception:
        exe_version = "unknown"

    print(f"  FreeCADCmd reports: {exe_version}")

    # Extract major.minor from both
    import re

    file_m = re.match(r"(\d+\.\d+)", file_version)
    exe_m = re.search(r"(\d+\.\d+)", exe_version)
    file_short = file_m.group(1) if file_m else file_version
    exe_short = exe_m.group(1) if exe_m else exe_version

    if file_short != exe_short:
        print(f"\n  WARNING: Version mismatch!")
        print(f"    File was created with: {file_version} (v{file_short})")
        print(f"    FreeCADCmd is:         {exe_version} (v{exe_short})")
        if not prompt_yes_no("  Continue anyway?", default=False):
            print(f"  Provide FreeCAD v{file_short} and try again.")
            return False
    else:
        print(f"  Version match: v{file_short}")

    stem = dest_path.stem
    baseline_path = BASELINE_DIR / f"{stem}.json"

    print(f"\n  Running FreeCAD to generate {baseline_path.name}...")

    with tempfile.TemporaryDirectory() as td:
        cfg = os.path.join(td, "config")
        os.makedirs(cfg)
        env = os.environ.copy()
        env["FREECAD_USER_HOME"] = cfg

        try:
            proc = subprocess.run(
                [freecad_exe, str(MACRO_PATH), str(dest_path), "--out", str(baseline_path)],
                capture_output=True,
                text=True,
                timeout=300,
                env=env,
            )
        except FileNotFoundError:
            print(f"  Error: FreeCADCmd not found at '{freecad_exe}'")
            return False
        except subprocess.TimeoutExpired:
            print("  Error: FreeCAD timed out after 300 seconds")
            return False

    if baseline_path.exists() and baseline_path.stat().st_size > 0:
        # Hard reject: a file that produces invalid geometry in its own native FreeCAD version is
        # unsuitable -- such latent BRep-invalid shapes are silently tolerated here but break in
        # stricter later versions.  scan_invalid_shapes in EvaluateFile walks EVERY object, so this
        # also catches invalid intermediate features that the final-solids grading misses.
        import json

        try:
            with open(baseline_path, "r", encoding="utf-8") as f:
                baseline_report = json.load(f)
        except Exception:
            baseline_report = {}
        invalid = baseline_report.get("invalid_shapes", [])
        if invalid:
            print(f"\n  REJECTED: {len(invalid)} object(s) have invalid geometry in the file's")
            print(f"  native FreeCAD version (BRep shape.isValid() is False):")
            for entry in invalid[:15]:
                name = entry.get("label") or entry.get("name", "?")
                print(f"    - {name} ({entry.get('type_id', '?')})")
            if len(invalid) > 15:
                print(f"    ... and {len(invalid) - 15} more")
            print("  Files with latent invalid geometry are not suitable for the test suite.")
            baseline_path.unlink(missing_ok=True)
            return False

        print(f"  Generated {baseline_path.name} ({baseline_path.stat().st_size / 1024:.1f} KB)")
        return True
    else:
        print(f"  Error: baseline not generated (rc={proc.returncode})")
        if proc.stderr:
            print(f"  stderr: {proc.stderr[-500:]}")
        return False


def step_run_test(dest_path: Path, freecad_exe: Optional[str]) -> bool:
    """Run the test suite for just this file to verify it passes.

    Args:
        dest_path: Path to the FCStd file in Data/CADFiles/.
        freecad_exe: Path to FreeCADCmd, or None to skip.

    Returns:
        True if the test passed.
    """
    print("\n--- Step 7: Verify test passes ---\n")

    if not freecad_exe:
        print("  Skipped (no FreeCADCmd path). Run manually before committing:")
        print(
            f"    python {TEST_RUNNER} --freecad /path/to/FreeCADCmd"
            f" --script {MACRO_PATH}"
            f" --fcstd-dir {CAD_DIR}"
            f" --baseline-dir {BASELINE_DIR}"
            f" --exceptions-dir {EXCEPTIONS_DIR}"
            f" --filename {dest_path.name} --verbose"
        )
        return False

    print(f"  Running test for {dest_path.name}...")

    proc = subprocess.run(
        [
            sys.executable,
            str(TEST_RUNNER),
            "--freecad",
            str(freecad_exe),
            "--script",
            str(MACRO_PATH),
            "--fcstd-dir",
            str(CAD_DIR),
            "--baseline-dir",
            str(BASELINE_DIR),
            "--exceptions-dir",
            str(EXCEPTIONS_DIR),
            "--filename",
            dest_path.name,
            "--verbose",
        ],
        capture_output=True,
        text=True,
        timeout=600,
    )

    print(proc.stdout[-1000:] if proc.stdout else "  (no output)")

    if proc.returncode == 0:
        print("  Test passed!")
        return True
    else:
        print(f"  Test failed (rc={proc.returncode}).")
        if proc.stderr:
            print(f"  stderr: {proc.stderr[-500:]}")
        return False


def step_credits_reminder(dest_name: str, metadata: Dict[str, str]) -> None:
    """Remind the user to update THIRD_PARTY_CREDITS.md and Tests.md.

    Args:
        dest_name: The test filename.
        metadata: The file's metadata dict.
    """
    print("\n--- Step 8: Documentation ---\n")

    credits_text = CREDITS_PATH.read_text(encoding="utf-8") if CREDITS_PATH.exists() else ""
    if dest_name in credits_text:
        print(f"  {dest_name} is already listed in THIRD_PARTY_CREDITS.md. OK.")
    else:
        print(f"  Remember to add {dest_name} to THIRD_PARTY_CREDITS.md")
        print(f"    Author:  {metadata.get('CreatedBy', '?')}")
        print(f"    License: {metadata.get('License', '?')}")
        print(f"    Source:  {metadata.get('Comment', '(original)')}")

    print(f"\n  Remember to add {dest_name} to Tests.md with a description.")


def _msys2_to_windows(path_str: str) -> str:
    """Translate MSYS2/Git Bash paths like /g/... to G:\\ on Windows.

    Args:
        path_str: A filesystem path string.

    Returns:
        The translated path, or the original if no translation applies.
    """
    if sys.platform == "win32" and len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == "/":
        return path_str[1].upper() + ":" + path_str[2:].replace("/", "\\")
    return path_str


def resolve_freecad_exe(freecad_exe: Optional[str]) -> Optional[str]:
    """Prompt for and resolve the FreeCADCmd executable path.

    Handles MSYS2/Git Bash paths (e.g. /g/FreeCAD/...) on Windows by resolving
    through Path.resolve(). Falls back to shutil.which() for bare command names.

    Args:
        freecad_exe: Path from --freecad argument, or None.

    Returns:
        The resolved absolute path as a string, or None if the user skips.
    """
    if not freecad_exe:
        freecad_exe = prompt(
            "  Path to FreeCADCmd (or press Enter to skip baseline generation and testing)"
        )

    if not freecad_exe:
        return None

    # Try shutil.which first (handles bare names like "FreeCADCmd" on PATH)
    resolved = shutil.which(freecad_exe)
    if resolved:
        return str(Path(resolved).resolve())

    p = Path(_msys2_to_windows(freecad_exe)).resolve()
    if p.is_file():
        return str(p)

    print(f"  Warning: FreeCADCmd not found at '{freecad_exe}'")
    if str(p) != freecad_exe:
        print(f"  (translated to: '{p}')")
    return None


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Interactive helper for adding a new FCStd test file."
    )
    parser.add_argument("fcstd", help="Path to the FCStd file to add")
    parser.add_argument(
        "--freecad",
        default=None,
        help="Path to FreeCADCmd executable (for baseline generation and testing)",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    """Run the interactive add-test-case workflow.

    Args:
        argv: Command-line arguments.

    Returns:
        0 on success, 1 on failure.
    """
    args = parse_args(argv)
    source_path = Path(_msys2_to_windows(args.fcstd)).resolve()

    if not source_path.is_file():
        print(f"Error: file not found: {source_path}")
        return 1

    if not source_path.suffix.lower() == ".fcstd":
        print(f"Error: expected an .FCStd file, got: {source_path.name}")
        return 1

    print(f"\nAdding test case: {source_path.name}")
    print("=" * 60)

    # Step 1-2: Inspect and fix metadata (work on a temp copy to avoid modifying the original)
    work_copy = source_path.parent / f".{source_path.name}.adding"
    shutil.copy2(str(source_path), str(work_copy))

    try:
        metadata = step_inspect_metadata(work_copy)
        metadata = step_fix_metadata(work_copy, metadata)

        # Step 3: Choose filename
        dest_name = step_choose_filename(source_path)

        # Step 4: Copy file
        dest_path = step_copy_file(work_copy, dest_name)

        # Step 5: Check license file
        step_check_license_file(metadata)

        # Resolve FreeCAD executable once for steps 6 and 7
        freecad_path = resolve_freecad_exe(args.freecad)

        # Step 6: Generate baseline
        baseline_ok = step_generate_baseline(dest_path, freecad_path, metadata)

        # Step 7: Run test
        test_ok = False
        if baseline_ok:
            test_ok = step_run_test(dest_path, freecad_path)

        # Handle failure: clean up and advise
        if freecad_path and not test_ok:
            print("\n" + "=" * 60)
            print("  The file did not pass the integration test.")
            print("  This usually means FreeCAD could not recompute the file")
            print("  consistently, or the file contains geometry errors.")
            print("")
            print("  Possible causes:")
            print("    - The file uses features not supported by this FreeCAD version")
            print("    - The file has broken references or missing dependencies")
            print("    - The file produces non-deterministic geometry on recompute")
            print("")

            if prompt_yes_no("  Remove the file from the test suite?", default=True):
                dest_path.unlink(missing_ok=True)
                baseline_path = BASELINE_DIR / f"{dest_path.stem}.json"
                baseline_path.unlink(missing_ok=True)
                print(f"  Removed {dest_path.name} and its baseline.")
                print("  Consider retrying with a different FreeCAD version,")
                print("  or fixing the file before adding it.")
            else:
                print("  Keeping the file. Fix the issues before committing.")

            return 1

        # Step 8: Documentation reminders
        step_credits_reminder(dest_name, metadata)

    finally:
        # Clean up temp copy
        if work_copy.exists():
            work_copy.unlink()

    print("\n" + "=" * 60)
    print("Done! Review the changes and commit when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
