"""Shared FreeCAD binary resolution for the integration test suite.

Single source of truth for FreeCADCmd paths, version parsing, macro selection,
and the pixi dev build directory. All scripts that need to locate a FreeCAD
binary should import from here rather than maintaining their own path constants.

Hardcoded with values from @chennes's main Windows build machine. You will need
to update them if you want to run the scripts for test evaluation etc. on your
own machine. This file is NOT used by the actual integration tests, which take
a path to a FreeCAD binary as a command-line argument.
"""

from __future__ import annotations

import atexit
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
MACRO_PATH = SCRIPT_DIR / "EvaluateFile.FCMacro"
MACRO_PATH_PY2 = SCRIPT_DIR / "EvaluateFilePy2.FCMacro"

SEVEN_ZIP = "C:\\Program Files\\7-Zip\\7z.exe"

# Directory containing pre-extracted releases and archived weekly builds.
PRECOMPILED_DIR = Path("G:/FreeCAD/Precompiled FreeCAD Binaries")

# Directory containing the pixi-based dev build of FreeCAD.
FREECAD_PIXI_DIR = Path("G:/FreeCAD/FreeCAD")

# FreeCAD versions that ship Python 2 and need the Py2 macro.
PY2_VERSIONS: Set[Tuple[int, int]] = {(0, 13), (0, 14), (0, 15), (0, 16), (0, 17)}

# Pre-extracted binaries keyed by (major, minor) version tuple.
_P = str(PRECOMPILED_DIR)
PORTABLE_BINARIES: Dict[Tuple[int, int], str] = {
    (0, 13): f"{_P}/FreeCAD-0.13/bin/FreeCADCmd.exe",
    (0, 14): f"{_P}/FreeCAD-0.14/bin/FreeCADCmd.exe",
    (0, 15): f"{_P}/FreeCAD-0.15/bin/FreeCADCmd.exe",
    (0, 16): f"{_P}/FreeCAD-0.16/bin/FreeCADCmd.exe",
    (0, 17): f"{_P}/FreeCAD-0.17/bin/FreeCADCmd.exe",
    (0, 18): f"{_P}/FreeCAD-0.18/bin/FreeCADCmd.exe",
    (0, 19): f"{_P}/FreeCAD-0.19/bin/FreeCADCmd.exe",
    (0, 20): f"{_P}/FreeCAD-0.20/bin/FreeCADCmd.exe",
    (0, 21): f"{_P}/FreeCAD-0.21/bin/FreeCADCmd.exe",
    (1, 0): f"{_P}/FreeCAD-1.0/bin/FreeCADCmd.exe",
    (1, 1): f"{_P}/FreeCAD-1.1/bin/FreeCADCmd.exe",
}

# Path to the latest stable release binary (used for "release_eval" runs).
# Update this when a newer release is published. We use os.path.normpath to
# ensure all separators are native (backslash on Windows), because FreeCADCmd
# 1.1.1 mis-parses argv when the exe path mixes \ and / and contains a space.
import os as _os  # noqa: E402

LATEST_RELEASE_VERSION = "1.1.1"
LATEST_RELEASE_EXE = _os.path.normpath(f"{_P}/FreeCAD_1.1.1-Windows-x86_64-py311/FreeCADCmd.exe")


def parse_version(version_string: str) -> Optional[Tuple[int, int]]:
    """Extract (major, minor) from a FreeCAD ProgramVersion string.

    Args:
        version_string: E.g. "1.0R38641 +468 (Git)" or "0.21R33771 (Git)".

    Returns:
        A (major, minor) tuple, or None if unparseable.
    """
    m = re.match(r"(\d+)\.(\d+)", version_string)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None


def needs_py2(version_string: str) -> bool:
    """Check whether a FreeCAD version requires the Python 2 macro.

    Args:
        version_string: ProgramVersion string from the FCStd file.

    Returns:
        True if the version ships Python 2 (0.13-0.17).
    """
    parsed = parse_version(version_string)
    return parsed is not None and parsed in PY2_VERSIONS


def macro_for_version(version_string: str) -> Path:
    """Return the appropriate macro path for a FreeCAD version.

    Args:
        version_string: ProgramVersion string from the FCStd file.

    Returns:
        MACRO_PATH_PY2 for FreeCAD 0.13-0.17, MACRO_PATH otherwise.
    """
    return MACRO_PATH_PY2 if needs_py2(version_string) else MACRO_PATH


# Cache of extracted precompiled binaries: archive_name -> extracted_dir
_extracted_cache: Dict[str, Path] = {}

# Temp dirs to clean up on exit
_temp_dirs: List[str] = []


def _cleanup_temps() -> None:
    for d in _temp_dirs:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


atexit.register(_cleanup_temps)


def _find_weekly_archive() -> Optional[Path]:
    """Find the most recent weekly build 7z archive.

    Returns:
        Path to the archive, or None.
    """
    if not PRECOMPILED_DIR.is_dir():
        return None

    candidates = [
        f for f in PRECOMPILED_DIR.iterdir() if f.name.endswith(".7z") and "weekly" in f.name
    ]

    if not candidates:
        return None
    candidates.sort(key=lambda p: p.name, reverse=True)
    return candidates[0]


def _extract_7z_archive(archive: Path) -> Optional[str]:
    """Extract a 7z archive to a temp directory, return the path to FreeCADCmd.exe.

    Caches extractions so the same archive is only extracted once per run.

    Args:
        archive: Path to the .7z archive.

    Returns:
        Path to FreeCADCmd.exe inside the extracted directory, or None on failure.
    """
    key = archive.name
    if key in _extracted_cache:
        exe = _extracted_cache[key] / "bin" / "FreeCADCmd.exe"
        if exe.is_file():
            return str(exe)
        return None

    tmpdir = tempfile.mkdtemp(prefix="fc_extract_")
    _temp_dirs.append(tmpdir)

    try:
        subprocess.run(
            [SEVEN_ZIP, "x", str(archive), f"-o{tmpdir}", "-y"],
            capture_output=True,
            timeout=300,
        )
    except Exception:
        return None

    # The archive extracts to a named subdirectory
    subdirectories = [d for d in Path(tmpdir).iterdir() if d.is_dir()]
    if len(subdirectories) == 1:
        extracted = subdirectories[0]
    else:
        extracted = Path(tmpdir)

    _extracted_cache[key] = extracted

    exe = extracted / "bin" / "FreeCADCmd.exe"
    if exe.is_file():
        return str(exe)
    return None


def resolve_freecad(version_string: str) -> Tuple[Optional[str], str]:
    """Find the best FreeCADCmd binary for a given ProgramVersion.

    Resolution order:
      1. Exact match in PORTABLE_BINARIES.
      2. Closest available installed version.
      3. Most recent weekly build archive (extracted on demand via 7-Zip).

    Args:
        version_string: The ProgramVersion from the FCStd file.

    Returns:
        (path_to_binary_or_None, resolution_method_string)
    """
    parsed = parse_version(version_string)
    if parsed is None:
        return str(PORTABLE_BINARIES.get((1, 1), "")), f"fallback (unparseable: {version_string})"

    major, minor = parsed

    # Exact match in installed binaries
    if parsed in PORTABLE_BINARIES:
        exe = PORTABLE_BINARIES[parsed]
        if Path(exe).is_file():
            return exe, f"installed {major}.{minor}"

    # Closest installed version
    available = sorted(PORTABLE_BINARIES.keys())
    best = None
    best_dist = 1000
    for v in available:
        dist = abs(v[0] * 100 + v[1] - major * 100 - minor)
        if dist < best_dist and Path(PORTABLE_BINARIES[v]).is_file():
            best = v
            best_dist = dist

    if best:
        return PORTABLE_BINARIES[best], f"closest installed {best[0]}.{best[1]}"

    # Last resort: extract the most recent weekly build
    archive = _find_weekly_archive()
    if archive:
        exe = _extract_7z_archive(archive)
        if exe:
            return exe, f"weekly {archive.name}"

    return None, "no binary found"
