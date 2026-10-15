"""Read logical lines from actual OOXML, joining only named adjacent spans."""
from __future__ import annotations

from xml.etree import ElementTree as ET

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"


def fact_blocks(root: ET.Element) -> list[str]:
    """One real text object/paragraph, or a named adjacent positioned line.

    Never concatenate arbitrary neighboring shapes or table cells. Authors may
    use one rich-text object for a metric and its value; normal reading order
    and visual geometry remain unconstrained outside that explicit fact.
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
    previous: tuple[str, int, int] | None = None
    for paragraph in root.iter(f"{{{A}}}p"):
        text = "".join("\n" if node.tag == f"{{{A}}}br" else (node.text or "") if node.tag == f"{{{A}}}t" else "" for node in paragraph.iter())
        owner = paragraph
        while owner in parents and owner.tag != f"{{{P}}}sp":
            owner = parents[owner]
        name = owner.find(f"./{{{P}}}nvSpPr/{{{P}}}cNvPr")
        off = owner.find(f"./{{{P}}}spPr/{{{A}}}xfrm/{{{A}}}off")
        ext = owner.find(f"./{{{P}}}spPr/{{{A}}}xfrm/{{{A}}}ext")
        group = name.get("name", "") if name is not None else ""
        positioned = group.startswith("sps-line:") and off is not None and ext is not None
        if positioned:
            try:
                x, y, width = int(off.get("x", "0")), int(off.get("y", "0")), int(ext.get("cx", "0"))
            except ValueError:
                positioned = False
        if positioned and previous and previous[0] == group and previous[1] == y and abs(previous[2] - x) <= 18288:
            pieces[-1] += text
        else:
            pieces.append(text)
        previous = (group, y, x + width) if positioned else None
    return "\n".join(pieces)
