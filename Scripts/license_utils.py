"""Shared license-handling utilities for the integration test suite.

Provides robust license string recognition (exact alias lookup + regex pattern matching),
incompatibility checking, and metadata for known open-source licenses. Used by both
CheckLicenses.py (CI validation) and AddTestCase.py (interactive helper).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set


@dataclass(frozen=True)
class LicenseInfo:
    """Metadata for a single known license.

    Attributes:
        spdx_id: SPDX-style identifier used as the canonical key and LICENSES/ filename stem.
        name: Human-readable display name.
        url: Canonical URL for the license.
        download_url: Direct URL for the plain-text license file (empty if unavailable).
        aliases: Lowercased exact-match strings found in FCStd metadata.
        pattern: Compiled regex for fuzzy matching against license strings.
    """

    spdx_id: str
    name: str
    url: str
    download_url: str = ""
    aliases: List[str] = field(default_factory=list)
    pattern: Optional[re.Pattern[str]] = None


# Common fragments used in multiple patterns.
_CC = r"(?:creative\s*commons|cc)"
_BY = r"(?:by|attribution)"
_SA = r"(?:[-\s]*(?:sa|sharealike))"
_SUFFIX = r"(?:\s+(?:international|int'?l|unported))?"
_SEP = r"\s*[-\s]*"


def _cc_pattern(version: str, sharealike: bool = False) -> re.Pattern[str]:
    """Build a compiled regex for a Creative Commons license variant.

    Args:
        version: Version string to match, e.g. "4" or "3".
        sharealike: If True, require the ShareAlike component.

    Returns:
        A compiled case-insensitive regex pattern.
    """
    sa_part = _SA if sharealike else ""
    # Negative lookahead prevents CC-BY from matching CC-BY-SA strings
    no_sa = "" if sharealike else r"(?![-\s]*(?:sa|sharealike))"
    expr = rf"{_CC}{_SEP}{_BY}{no_sa}{sa_part}{_SEP}{version}[\.\s]*0{_SUFFIX}"
    return re.compile(expr, re.IGNORECASE)


def _cc_bare_pattern(sharealike: bool = False) -> re.Pattern[str]:
    """Build a regex for a versionless Creative Commons string (defaults to 4.0).

    Args:
        sharealike: If True, require the ShareAlike component.

    Returns:
        A compiled case-insensitive regex pattern.
    """
    sa_part = _SA if sharealike else ""
    no_sa = "" if sharealike else r"(?![-\s]*(?:sa|sharealike))"
    # Match "Creative Commons Attribution" or "CC BY" without a version number
    expr = rf"^{_CC}{_SEP}{_BY}{no_sa}{sa_part}\s*$"
    return re.compile(expr, re.IGNORECASE)


# ORDER MATTERS: more-specific entries (CC-BY-SA) must come before less-specific
# ones (CC-BY) so that regex matching returns the correct result on first hit.

KNOWN_LICENSES: List[LicenseInfo] = [
    # --- Creative Commons ---
    LicenseInfo(
        spdx_id="CC0-1.0",
        name="Creative Commons Zero v1.0 Universal",
        url="https://creativecommons.org/publicdomain/zero/1.0/",
        download_url="https://creativecommons.org/publicdomain/zero/1.0/legalcode.txt",
        aliases=[
            "cc0",
            "cc0-1.0",
            "cc0 1.0",
            "cc0 1.0 universal",
            "creative commons zero",
            "creative commons zero 1.0",
            "creative commons zero 1.0 universal",
        ],
        pattern=re.compile(
            # Require an actual CC0 identifier (not a bare "0", which would
            # otherwise match the "0" in version strings like "v3.0").
            r"(?:creative\s*commons\s+zero|cc\s*[-_]?\s*0)"
            r"(?:\s*[-_]?\s*v?\s*1[\.\s]*0)?"
            r"(?:\s+universal)?",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="CC-BY-SA-4.0",
        name="Creative Commons Attribution-ShareAlike 4.0 International",
        url="https://creativecommons.org/licenses/by-sa/4.0/",
        download_url="https://creativecommons.org/licenses/by-sa/4.0/legalcode.txt",
        aliases=[
            "cc-by-sa-4.0",
            "cc-by-sa 4.0",
            "cc by-sa 4.0",
            "creative commons attribution-sharealike",
            "creative commons attribution-sharealike 4.0",
            "creative commons attribution-sharealike 4.0 international",
            "creativecommons attribution-sharealike",
        ],
        pattern=_cc_pattern("4", sharealike=True),
    ),
    LicenseInfo(
        spdx_id="CC-BY-4.0",
        name="Creative Commons Attribution 4.0 International",
        url="https://creativecommons.org/licenses/by/4.0/",
        download_url="https://creativecommons.org/licenses/by/4.0/legalcode.txt",
        aliases=[
            "cc-by-4.0",
            "cc-by 4.0",
            "cc by 4.0",
            "creative commons attribution",
            "creative commons attribution 4.0",
            "creative commons attribution 4.0 international",
            "creativecommons attribution",
        ],
        pattern=_cc_pattern("4", sharealike=False),
    ),
    LicenseInfo(
        spdx_id="CC-BY-3.0",
        name="Creative Commons Attribution 3.0 Unported",
        url="https://creativecommons.org/licenses/by/3.0/",
        download_url="https://creativecommons.org/licenses/by/3.0/legalcode.txt",
        aliases=[
            "cc-by-3.0",
            "cc-by 3.0",
            "cc by 3.0",
            "creative commons attribution 3.0",
            "creative commons attribution 3.0 unported",
        ],
        pattern=_cc_pattern("3", sharealike=False),
    ),
    # --- GNU ---
    LicenseInfo(
        spdx_id="LGPL-2.1-or-later",
        name="GNU Lesser General Public License v2.1 or later",
        url="https://www.gnu.org/licenses/old-licenses/lgpl-2.1.html",
        download_url="https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt",
        aliases=[
            "lgpl-2.1",
            "lgpl-2.1-or-later",
            # FreeCAD Parts Library parts declare their license as "same as FreeCAD",
            # i.e. FreeCAD's software license, LGPL-2.1-or-later (decision 2026-06-04).
            "(same license as freecad)",
            "same license as freecad",
            "same as freecad",
        ],
        pattern=re.compile(
            r"(?:gnu\s+)?(?:lesser\s+)?(?:general\s+public\s+licen[cs]e\s+)?"
            r"lgpl\s*[-\s]*2[\.\s]*1(?:\s*[-\s]*or\s*[-\s]*later)?",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="GPL-3.0-or-later",
        name="GNU General Public License v3.0 or later",
        url="https://www.gnu.org/licenses/gpl-3.0.html",
        download_url="https://www.gnu.org/licenses/gpl-3.0.txt",
        aliases=[
            "gpl-3.0",
            "gpl-3.0-or-later",
            "gpl-3",
            "gplv3",
            "gnu general public license v3.0 or later",
            "gnu general public license v3.0",
            "gnu general public license v3",
            "gnu general public license version 3",
            "gnu gpl v3",
            "gnu gpl version 3",
        ],
        pattern=re.compile(
            # Negative lookbehind on the "gpl" alternative blocks "lgpl" from matching.
            r"(?:gnu\s+)?(?:general\s+public\s+licen[cs]e|(?<!l)gpl)"
            r"\s*[-\s,]*(?:v(?:ersion)?\s*)?3(?:[\.\s]*0)?"
            r"(?:\s*[-\s]*or\s*[-\s]*later)?",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="GPL-2.0-or-later",
        name="GNU General Public License v2.0 or later",
        url="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html",
        download_url="https://www.gnu.org/licenses/old-licenses/gpl-2.0.txt",
        aliases=[
            "gpl-2.0",
            "gpl-2.0-or-later",
            "gpl-2",
            "gplv2",
            "gnu general public license v2.0 or later",
            "gnu general public license v2.0",
            "gnu general public license v2",
            "gnu general public license version 2",
            "gnu gpl v2",
            "gnu gpl version 2",
        ],
        pattern=re.compile(
            r"(?:gnu\s+)?(?:general\s+public\s+licen[cs]e|(?<!l)gpl)"
            r"\s*[-\s,]*(?:v(?:ersion)?\s*)?2(?:[\.\s]*0)?"
            r"(?:\s*[-\s]*or\s*[-\s]*later)?",
            re.IGNORECASE,
        ),
    ),
    # --- Permissive licenses ---
    LicenseInfo(
        spdx_id="MIT",
        name="MIT License",
        url="https://opensource.org/license/mit/",
        aliases=[
            "mit",
            "mit license",
            "the mit license",
            "mit-license",
        ],
        pattern=re.compile(r"\bmit(?:\s+licen[cs]e)?\b", re.IGNORECASE),
    ),
    LicenseInfo(
        spdx_id="Apache-2.0",
        name="Apache License 2.0",
        url="https://www.apache.org/licenses/LICENSE-2.0",
        download_url="https://www.apache.org/licenses/LICENSE-2.0.txt",
        aliases=[
            "apache-2.0",
            "apache 2.0",
            "apache license 2.0",
            "apache license, version 2.0",
            "apache software license 2.0",
        ],
        pattern=re.compile(
            r"apache(?:\s+(?:software\s+)?licen[cs]e)?(?:[,\s]+version)?\s*[-\s]*2[\.\s]*0",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="BSD-3-Clause",
        name="BSD 3-Clause License",
        url="https://opensource.org/license/bsd-3-clause/",
        aliases=[
            "bsd-3-clause",
            "bsd 3-clause",
            "bsd 3 clause",
            "bsd 3-clause license",
            "new bsd license",
            "modified bsd license",
        ],
        pattern=re.compile(r"bsd\s*[-\s]*3(?:\s*[-\s]*clause)?", re.IGNORECASE),
    ),
    # --- CERN Open Hardware Licence ---
    LicenseInfo(
        spdx_id="CERN-OHL-S-2.0",
        name="CERN Open Hardware Licence v2 -- Strongly Reciprocal",
        url="https://ohwr.org/cernohl",
        aliases=[
            "cern-ohl-s-2.0",
            "cern ohl s 2.0",
            "cern ohl v2 strongly reciprocal",
            "cern open hardware licence version 2 - strongly reciprocal",
        ],
        pattern=re.compile(
            r"cern\s+(?:open\s+hardware\s+licen[cs]e\s+)?"
            r"(?:o\.?h\.?l\.?\s*)?(?:v(?:ersion)?\s*)?[-\s]*"
            r"(?:s(?:trongly)?(?:\s*[-\s]*reciprocal)?)\s*[-\s]*2[\.\s]*0",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="CERN-OHL-W-2.0",
        name="CERN Open Hardware Licence v2 -- Weakly Reciprocal",
        url="https://ohwr.org/cernohl",
        aliases=[
            "cern-ohl-w-2.0",
            "cern ohl w 2.0",
            "cern ohl v2 weakly reciprocal",
            "cern open hardware licence version 2 - weakly reciprocal",
        ],
        pattern=re.compile(
            r"cern\s+(?:open\s+hardware\s+licen[cs]e\s+)?"
            r"(?:o\.?h\.?l\.?\s*)?(?:v(?:ersion)?\s*)?[-\s]*"
            r"(?:w(?:eakly)?(?:\s*[-\s]*reciprocal)?)\s*[-\s]*2[\.\s]*0",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="CERN-OHL-P-2.0",
        name="CERN Open Hardware Licence v2 -- Permissive",
        url="https://ohwr.org/cernohl",
        aliases=[
            "cern-ohl-p-2.0",
            "cern ohl p 2.0",
            "cern ohl v2 permissive",
            "cern open hardware licence version 2 - permissive",
        ],
        pattern=re.compile(
            r"cern\s+(?:open\s+hardware\s+licen[cs]e\s+)?"
            r"(?:o\.?h\.?l\.?\s*)?(?:v(?:ersion)?\s*)?[-\s]*"
            r"(?:p(?:ermissive)?)\s*[-\s]*2[\.\s]*0",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="CERN-OHL-1.2",
        name="CERN Open Hardware Licence v1.2",
        url="https://ohwr.org/cernohl",
        aliases=[
            "cern ohl v1.2",
            "cern open hardware licence v1.2",
            "cern-ohl-1.2",
        ],
        pattern=re.compile(
            r"cern\s+(?:open\s+hardware\s+licen[cs]e\s+)?" r"(?:o\.?h\.?l\.?\s*)?v?\s*1[\.\s]*2",
            re.IGNORECASE,
        ),
    ),
    LicenseInfo(
        spdx_id="CERN-OHL-1.1",
        name="CERN Open Hardware Licence v1.1",
        url="https://ohwr.org/cernohl",
        aliases=[
            "cern ohl v1.1",
            "cern open hardware licence v1.1",
            "cern-ohl-1.1",
        ],
        pattern=re.compile(
            r"cern\s+(?:open\s+hardware\s+licen[cs]e\s+)?" r"(?:o\.?h\.?l\.?\s*)?v?\s*1[\.\s]*1",
            re.IGNORECASE,
        ),
    ),
    # --- Public Domain ---
    LicenseInfo(
        spdx_id="PUBLIC-DOMAIN",
        name="Public Domain",
        url="https://en.wikipedia.org/wiki/Public_domain",
        aliases=["public domain"],
        pattern=re.compile(r"public\s*domain", re.IGNORECASE),
    ),
]

# Build the fast exact-match lookup from all aliases.
_ALIAS_MAP: Dict[str, str] = {}
for _lic in KNOWN_LICENSES:
    for _alias in _lic.aliases:
        _ALIAS_MAP[_alias] = _lic.spdx_id

# Build a lookup by SPDX ID.
_SPDX_MAP: Dict[str, LicenseInfo] = {lic.spdx_id: lic for lic in KNOWN_LICENSES}

INCOMPATIBLE_PATTERNS: List[str] = [
    "noncommercial",
    "non-commercial",
    "all rights reserved",
    "no derivatives",
    "no-derivatives",
]


def normalize_license(license_str: str) -> Optional[str]:
    """Map a license string to its canonical SPDX-style identifier.

    Uses a two-tier strategy:
      1. Exact alias lookup (fast, covers all known spellings).
      2. Regex pattern matching (handles novel variations).

    Args:
        license_str: Raw license string from FCStd file metadata.

    Returns:
        The SPDX identifier (e.g. "CC-BY-4.0"), or None if unrecognized.
    """
    cleaned = license_str.strip().lower()
    if not cleaned:
        return None

    # Tier 1: exact alias lookup
    spdx = _ALIAS_MAP.get(cleaned)
    if spdx is not None:
        return spdx

    # Tier 2: regex pattern matching (order matters -- more specific first)
    for lic in KNOWN_LICENSES:
        if lic.pattern is not None and lic.pattern.search(cleaned):
            return lic.spdx_id

    return None


def is_incompatible(license_str: str) -> bool:
    """Check whether a license string indicates an incompatible license.

    Looks for substring matches against known incompatible patterns such as
    "noncommercial", "no derivatives", and "all rights reserved".

    Args:
        license_str: Raw license string from FCStd file metadata.

    Returns:
        True if the license is not compatible with redistribution in this suite.
    """
    lower = license_str.strip().lower()
    return any(pat in lower for pat in INCOMPATIBLE_PATTERNS)


def is_placeholder(license_str: str) -> bool:
    """Check whether a license string is a generic placeholder.

    FreeCAD defaults to "All rights reserved" when no license is explicitly set.
    This function detects that default and empty strings.

    Args:
        license_str: Raw license string from FCStd file metadata.

    Returns:
        True if the string is empty or is the FreeCAD default "All rights reserved".
    """
    lower = license_str.strip().lower()
    return not lower or lower == "all rights reserved"


def get_license_info(spdx_id: str) -> Optional[LicenseInfo]:
    """Look up license metadata by SPDX identifier.

    Args:
        spdx_id: The canonical SPDX-style identifier (e.g. "CC-BY-4.0").

    Returns:
        The LicenseInfo dataclass, or None if the identifier is not known.
    """
    return _SPDX_MAP.get(spdx_id)


def all_spdx_ids() -> List[str]:
    """Return all known SPDX identifiers in registry order.

    Returns:
        A list of SPDX-style identifier strings.
    """
    return [lic.spdx_id for lic in KNOWN_LICENSES]


def available_license_files(licenses_dir: Path) -> Set[str]:
    """Scan a directory for license text files and return their stem names.

    Args:
        licenses_dir: Path to the LICENSES/ directory.

    Returns:
        A set of filename stems (e.g. {"CC-BY-4.0", "LGPL-2.1-or-later"}).
    """
    if not licenses_dir.is_dir():
        return set()
    return {f.stem for f in licenses_dir.iterdir() if f.is_file()}
