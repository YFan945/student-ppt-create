"""Read logical lines from actual OOXML, joining spans that share one named line."""
from __future__ import annotations

from xml.etree import ElementTree as ET

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def fact_blocks(root: ET.Element) -> list[str]:
    """One real text object/paragraph, or one named positioned line.

    Fragments emitted by `addPositionedText` share the line's `sps-line:` shape
    name; they re-join by that name alone. Baseline alignment gives fragments
    of one line different y offsets, and language spans are separated by
    measured gaps, so geometry must not gate the re-join. Unrelated shapes and
    table cells are never concatenated. Normal reading order and visual
    geometry remain unconstrained outside an explicit fact.
    """
    blocks = slide_text(root).splitlines()
    for shape in root.iter(f"{{{P}}}sp"):
        body = shape.find(f"{{{P}}}txBody")
        if body is not None:
            blocks.append(slide_text(body))
    blocks.extend(associated_text(root))
    return list(dict.fromkeys(block for block in blocks if block.strip()))


def associated_text(root: ET.Element) -> list[str]:
    """Associate unambiguous neighbouring label/value shapes, never whole pages.

    Only mutual nearest neighbours in the same shape-tree container qualify.
    Existing numeric labels cannot absorb another metric's value. Table cells
    are paired within their actual row. Ambiguous cards stay for author review.
    """
    import re

    from shared.content_requirements import NUMBER_RE

    result = []
    for tree in root.iter():
        if tree.tag not in {f"{{{P}}}spTree", f"{{{P}}}grpSp"}:
            continue
        shapes = []
        for shape in tree.findall(f"{{{P}}}sp"):
            text = slide_text(shape).strip()
            xfrm = shape.find(f"./{{{P}}}spPr/{{{A}}}xfrm")
            if not text or xfrm is None or xfrm.get("rot", "0") != "0":
                continue
            off, ext = xfrm.find(f"{{{A}}}off"), xfrm.find(f"{{{A}}}ext")
            if off is None or ext is None:
                continue
            x, y, w, h = (int(node.get(key, "0")) / 914400 for node, key in
                          ((off, "x"), (off, "y"), (ext, "cx"), (ext, "cy")))
            if w > 0 and h > 0:
                shapes.append((text, x, y, w, h))
        candidates = []
        for i, label in enumerate(shapes):
            if NUMBER_RE.search(label[0]) or len(label[0]) > 80:
                continue
            for j, quantity in enumerate(shapes):
                if i == j or not re.match(r"^\s*[+-]?\d", quantity[0]):
                    continue
                _, x, y, w, h = label
                _, qx, qy, qw, qh = quantity
                row_overlap = min(y + h, qy + qh) - max(y, qy)
                column_overlap = min(x + w, qx + qw) - max(x, qx)
                right_gap, bottom_gap = qx - x - w, qy - y - h
                if row_overlap >= min(h, qh) * 0.5 and -0.02 <= right_gap <= 0.6:
                    candidates.append((right_gap, i, j))
                elif column_overlap >= min(w, qw) * 0.5 and -0.02 <= bottom_gap <= 0.35:
                    candidates.append((bottom_gap, i, j))
        for distance, i, j in candidates:
            competing = [d for d, a, b in candidates if (a == i or b == j) and (a, b) != (i, j)]
            if competing and min(competing) <= distance + 0.05:
                continue
            result.append(shapes[i][0] + ":" + shapes[j][0])
    for row in root.iter(f"{{{A}}}tr"):
        cells = [slide_text(cell).strip() for cell in row.findall(f"{{{A}}}tc")]
        if len(cells) == 2 and cells[0] and not NUMBER_RE.search(cells[0]):
            result.append(cells[0] + ":" + cells[1])
    return result


def slide_text(root: ET.Element) -> str:
    parents = {child: parent for parent in root.iter() for child in parent}
    pieces: list[str] = []
    previous_group = ""
    for paragraph in root.iter(f"{{{A}}}p"):
        text = "".join("\n" if node.tag == f"{{{A}}}br" else (node.text or "") if node.tag == f"{{{A}}}t" else "" for node in paragraph.iter())
        owner = paragraph
        while owner in parents and owner.tag != f"{{{P}}}sp":
            owner = parents[owner]
        name = owner.find(f"./{{{P}}}nvSpPr/{{{P}}}cNvPr")
        group = name.get("name", "") if name is not None else ""
        positioned = group.startswith("sps-line:")
        if positioned and group == previous_group:
            pieces[-1] += text
        else:
            pieces.append(text)
        previous_group = group if positioned else ""
    return "\n".join(pieces)
