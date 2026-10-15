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
    return list(dict.fromkeys(block for block in blocks if block.strip()))


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
