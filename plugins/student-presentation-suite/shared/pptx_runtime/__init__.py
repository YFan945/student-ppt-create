"""PPTX-only runtime owned by student-presentation-suite."""

from .cjk_fonts import apply_cjk_fonts, parse_font_map
from .edit import add_slide, clean_package, delete_slide, reorder_slides
from .fetch_images import fetch_images
from .package import pack_directory, safe_extract_package
from .validate import validate_pptx
from .visual_baseline import compare_baseline, record_baseline

__all__ = [
    "add_slide",
    "apply_cjk_fonts",
    "fetch_images",
    "record_baseline",
    "compare_baseline",
    "parse_font_map",
    "clean_package",
    "delete_slide",
    "pack_directory",
    "reorder_slides",
    "safe_extract_package",
    "validate_pptx",
]
