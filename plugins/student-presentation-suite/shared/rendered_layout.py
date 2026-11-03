"""Find collisions in actual rendered text positions, without scoring style."""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from defusedxml import ElementTree as ET

from shared.pptx_runtime.render import find_pdftoppm


def inspect_pdf(pdf: Path, intentional_regions: dict[int, list[tuple]] | None = None) -> dict:
    ppm = find_pdftoppm()
    sibling = Path(ppm).with_name("pdftotext.exe" if os.name == "nt" else "pdftotext") if ppm else None
    executable = str(sibling) if sibling and sibling.is_file() else shutil.which("pdftotext")
    if not executable:
        return {"performed": False, "errors": [], "limitation": "pdftotext unavailable; inspect rendered images directly."}
    result = subprocess.run([executable, "-bbox-layout", str(pdf), "-"], capture_output=True, timeout=60)
    if result.returncode:
        return {"performed": False, "errors": [], "limitation": "Rendered text positions unavailable; inspect images directly."}
    try:
        # Poppler emits an XHTML doctype, but no external data is needed.
        root = ET.fromstring(result.stdout)
    except ET.ParseError:
        return {"performed": False, "errors": [], "limitation": "Unrecognized rendered text positions."}
    return inspect_boxes(root, intentional_regions)


def inspect_boxes(root, intentional_regions: dict[int, list[tuple]] | None = None) -> dict:
    errors = []
    for page_number, page in enumerate(root.findall(".//{*}page"), 1):
        lines = []
        for line in page.findall(".//{*}line"):
            words = [(str(word.text or ""), tuple(float(word.attrib[key]) for key in ("xMin", "yMin", "xMax", "yMax")))
                     for word in line.findall("{*}word") if str(word.text or "").strip()]
            if words:
                lines.append(words)
        for index, first in enumerate(lines):
            for second in lines[index + 1:]:
                collision = None
                for text_a, a in first:
                    for text_b, b in second:
                        width = min(a[2] - a[0], b[2] - b[0])
                        height = min(a[3] - a[1], b[3] - b[1])
                        dx, dy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
                        # Font ascender boxes can touch between normal lines.
                        # Require substantial horizontal AND vertical intrusion.
                        if width > 0 and height > 0 and dx > max(2, width * .35) and dy > height * .4:
                            x, y = max(a[0], b[0]), max(a[1], b[1])
                            # Renderer glyph bearings can extend a fraction of
                            # a point outside the authored box.
                            if any(left - 1 <= x and top - 1 <= y and x + dx <= right + 1 and y + dy <= bottom + 1
                                   for left, top, right, bottom in (intentional_regions or {}).get(page_number, (intentional_regions or {}).get(str(page_number), []))):
                                continue
                            collision = {"text_a": text_a[:90], "text_b": text_b[:90],
                                         "intersection_pt": [max(a[0], b[0]), max(a[1], b[1]), dx, dy]}
                            break
                    if collision:
                        break
                if collision:
                    errors.append({"slide": page_number, "code": "rendered_text_overlap", "basis": "rendered-text-positions", **collision})
    return {"performed": True, "errors": errors, "limitation": "Rendered text positions detect substantial collisions, not image/chart occlusion or overall visual quality."}
