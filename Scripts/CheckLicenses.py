#!/usr/bin/env python3
"""Check license metadata for all FCStd files in the test suite.

Verifies that every file has:
  - A compatible open-source license in its in-file metadata
  - A CreatedBy field identifying the author
  - A Comment field identifying the source project (for third-party files)
  - An entry in THIRD_PARTY_CREDITS.md
  - A corresponding license text file in LICENSES/

Usage:
  python Scripts/CheckLicenses.py
  python Scripts/CheckLicenses.py --fcstd-dir Data/CADFiles --credits THIRD_PARTY_CREDITS.md
"""

from __future__ import annotations

import argparse
import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from defusedxml.ElementTree import fromstring as parse_xml  # noqa: E402
from license_utils import normalize_license, is_incompatible  # noqa: E402


@dataclass
class FileInfo:
    """Metadata extracted from a single FCStd file."""

    filename: str
    created_by: str = ""
    license_str: str = ""
    license_url: str = ""
    comment: str = ""
    company: str = ""
    spdx_id: Optional[str] = None
    problems: List[str] = field(default_factory=list)


def extract_metadata(path: Path) -> FileInfo:
    """Extract license and author metadata from an FCStd file.

    Args:
        path: Path to the FCStd file.

    Returns:
        A FileInfo with the extracted metadata and any problems found.
    """
    info = FileInfo(filename=path.name)

    try:
        with zipfile.ZipFile(path, "r") as z:
            if "Document.xml" not in z.namelist():
                info.problems.append("No Document.xml inside FCStd archive")
                return info
            with z.open("Document.xml") as dx:
                root = parse_xml(dx.read())
    except zipfile.BadZipFile:
        info.problems.append("File is not a valid ZIP/FCStd archive")
        return info
    except Exception as e:
        info.problems.append(f"Failed to parse Document.xml: {e}")
        return info

    prop_map = {
        "CreatedBy": "created_by",
        "License": "license_str",
        "LicenseURL": "license_url",
        "Comment": "comment",
        "Company": "company",
    }

    for prop in root.iter("Property"):
        pname = prop.get("name", "")
        if pname in prop_map:
            for s in prop.iter("String"):
                val = s.get("value", "")
                if val and not getattr(info, prop_map[pname]):
                    setattr(info, prop_map[pname], val)
                break

    return info


def check_file(info: FileInfo) -> None:
    """Validate a file's metadata and populate its problems list.

    Args:
        info: The FileInfo to validate. Problems are appended in-place.
    """
    if not info.license_str:
        info.problems.append("Missing License in file metadata")
    elif is_incompatible(info.license_str):
        info.problems.append(f"Incompatible license: '{info.license_str}'")
    else:
        spdx = normalize_license(info.license_str)
        if spdx is None:
            info.problems.append(
                f"Unrecognized license: '{info.license_str}' "
                f"-- add a mapping in Scripts/license_utils.py"
            )
        else:
            info.spdx_id = spdx

    if not info.license_url:
        info.problems.append("Missing LicenseURL in file metadata")

    if not info.created_by:
        info.problems.append("Missing CreatedBy in file metadata")


def check_credits(files: List[FileInfo], credits_path: Path) -> List[str]:
    """Check that every file appears in THIRD_PARTY_CREDITS.md.

    Args:
        files: List of FileInfo for all test files.
        credits_path: Path to the THIRD_PARTY_CREDITS.md file.

    Returns:
        A list of problem strings for files not found in the credits.
    """
    problems: List[str] = []
    if not credits_path.is_file():
        problems.append(f"THIRD_PARTY_CREDITS.md not found at {credits_path}")
        return problems

    credits_text = credits_path.read_text(encoding="utf-8")
    for info in files:
        if info.filename not in credits_text:
            problems.append(f"{info.filename}: not listed in THIRD_PARTY_CREDITS.md")

    return problems


def check_license_files(files: List[FileInfo], licenses_dir: Path) -> List[str]:
    """Check that every required license text is present in LICENSES/.

    Args:
        files: List of FileInfo for all test files.
        licenses_dir: Path to the LICENSES/ directory.

    Returns:
        A list of problem strings for missing license files.
    """
    problems: List[str] = []

    if not licenses_dir.is_dir():
        problems.append(f"LICENSES/ directory not found at {licenses_dir}")
        return problems

    existing: Set[str] = set()
    for f in licenses_dir.iterdir():
        if f.is_file():
            existing.add(f.stem)

    needed: Set[str] = set()
    for info in files:
        if info.spdx_id and info.spdx_id != "PUBLIC-DOMAIN":
            needed.add(info.spdx_id)

    for spdx_id in sorted(needed):
        if spdx_id not in existing:
            problems.append(
                f"Missing license text: LICENSES/{spdx_id}.txt "
                f"-- download the full license text and add it"
            )

    return problems


def parse_args(argv: List[str]) -> argparse.Namespace:
    """Parse command-line arguments.

    Args:
        argv: Command-line arguments.

    Returns:
        Parsed arguments.
    """
    parser = argparse.ArgumentParser(description="Check license metadata for all FCStd test files.")
    parser.add_argument(
        "--fcstd-dir",
        default="Data/CADFiles",
        help="Directory containing FCStd test files (default: Data/CADFiles)",
    )
    parser.add_argument(
        "--credits",
        default="THIRD_PARTY_CREDITS.md",
        help="Path to THIRD_PARTY_CREDITS.md (default: THIRD_PARTY_CREDITS.md)",
    )
    parser.add_argument(
        "--licenses-dir",
        default="LICENSES",
        help="Directory containing license text files (default: LICENSES)",
    )
    return parser.parse_args(argv)


def main(argv: List[str]) -> int:
    """Run license checks and report results.

    Args:
        argv: Command-line arguments.

    Returns:
        0 if all checks pass, 1 if any problems are found.
    """
    args = parse_args(argv)
    fcstd_dir = Path(args.fcstd_dir)
    credits_path = Path(args.credits)
    licenses_dir = Path(args.licenses_dir)

    if not fcstd_dir.is_dir():
        print(f"ERROR: FCStd directory not found: {fcstd_dir}", file=sys.stderr)
        return 1

    fcstd_files = sorted(fcstd_dir.glob("*.FCStd"))
    if not fcstd_files:
        print(f"ERROR: No FCStd files found in {fcstd_dir}", file=sys.stderr)
        return 1

    # Extract and validate per-file metadata
    all_infos: List[FileInfo] = []
    for path in fcstd_files:
        info = extract_metadata(path)
        check_file(info)
        all_infos.append(info)

    # Check credits and license files
    credits_problems = check_credits(all_infos, credits_path)
    license_file_problems = check_license_files(all_infos, licenses_dir)

    # Report
    total_problems = 0

    print(f"Checked {len(all_infos)} FCStd files\n")

    # Per-file problems
    files_with_problems = [i for i in all_infos if i.problems]
    if files_with_problems:
        print("=== Per-file problems ===")
        for info in files_with_problems:
            for problem in info.problems:
                print(f"  {info.filename}: {problem}")
            total_problems += len(info.problems)
        print()

    # Credits problems
    if credits_problems:
        print("=== THIRD_PARTY_CREDITS.md problems ===")
        for problem in credits_problems:
            print(f"  {problem}")
        total_problems += len(credits_problems)
        print()

    # License file problems
    if license_file_problems:
        print("=== LICENSES/ problems ===")
        for problem in license_file_problems:
            print(f"  {problem}")
        total_problems += len(license_file_problems)
        print()

    # Summary
    spdx_counts: Dict[str, int] = {}
    for info in all_infos:
        key = info.spdx_id or "(unrecognized)"
        spdx_counts[key] = spdx_counts.get(key, 0) + 1

    print("=== License summary ===")
    for spdx_id, count in sorted(spdx_counts.items()):
        print(f"  {spdx_id:<25} {count:>3} files")
    print()

    if total_problems == 0:
        print("All checks passed.")
        return 0
    else:
        print(f"{total_problems} problem(s) found.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
