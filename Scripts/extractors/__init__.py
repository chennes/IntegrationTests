"""Registry of metric extractors for the integration test suite.

Each extractor is a (section_name, extractor_function) tuple.  All sections use the same
name-based extraction pattern via make_simple_extractor.
"""

from __future__ import annotations

from typing import List, Tuple

from metric_types import ExtractorFunction, make_simple_extractor

EXTRACTORS: List[Tuple[str, ExtractorFunction]] = [
    ("solids", make_simple_extractor("solids")),
    ("sketches", make_simple_extractor("sketches")),
    ("partdesign_bodies", make_simple_extractor("partdesign_bodies")),
    ("partdesign_features", make_simple_extractor("partdesign_features")),
    ("part_features", make_simple_extractor("part_features")),
    ("app_parts", make_simple_extractor("app_parts")),
    ("assemblies", make_simple_extractor("assemblies")),
    ("techdraw_pages", make_simple_extractor("techdraw_pages")),
    ("spreadsheets", make_simple_extractor("spreadsheets")),
    ("links", make_simple_extractor("links")),
    ("part_extrusions", make_simple_extractor("part_extrusions")),
    ("materials", make_simple_extractor("materials")),
]
