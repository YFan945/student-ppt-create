#!/usr/bin/env python3
"""Developer-only build of portable reference recipes; never copies PPTX/fonts.

Read user-provided examples without executing any contained text or macros.
Preserve source previews and attribution; collect native layout data only.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.hashing import file_sha256  # noqa: E402
from shared.pptx_runtime.package import relationship_part, resolve_target  # noqa: E402
from shared.template_library import ROLES, A, P, R, _key  # noqa: E402

EMU = 914400
NS = {"p": P, "a": A}


def _xml(archive: zipfile.ZipFile, part: str):
    info = archive.getinfo(part)
    if info.file_size > 16 * 1024 * 1024:
        raise ValueError(f"reference XML too large: {part}")
    return ET.fromstring(archive.read(part))


def _fill(node) -> dict[str, Any]:
    if node is None:
        return {}
    result = {}
    for kind in ("srgbClr", "schemeClr"):
        color = node.find(f".//a:{kind}", NS)
        if color is not None:
            result[kind] = color.get("val")
            alpha = color.find("a:alpha", NS)
            if alpha is not None:
                result["opacity"] = int(alpha.get("val")) / 100000
            break
    return result


def _bounds(node) -> dict[str, Any]:
    if node is None:
        return {}
    value: dict[str, Any] = {}
    for child, keys in (("off", ("x", "y")), ("ext", ("cx", "cy")),
                        ("chOff", ("x", "y")), ("chExt", ("cx", "cy"))):
        item = node.find(f"a:{child}", NS)
        if item is not None:
            value[child] = {key: round(int(item.get(key, "0")) / EMU, 5) for key in keys}
    for key in ("rot", "flipH", "flipV"):
        if node.get(key):
            value[key] = int(node.get(key)) / 60000 if key == "rot" else node.get(key)
    return value


def _objects(tree) -> list[dict[str, Any]]:
    result = []
    if tree is None:
        return result
    for order, element in enumerate(tree):
        kind = element.tag.rsplit("}", 1)[-1]
        if kind not in {"sp", "pic", "grpSp", "cxnSp", "graphicFrame"}:
            continue
        ident = element.find(".//p:cNvPr", NS)
        shape = {"kind": kind, "order": order, "name": ident.get("name", "") if ident is not None else ""}
        xfrm = next((element.find(path, NS) for path in ("p:spPr/a:xfrm", "p:grpSpPr/a:xfrm", "p:xfrm")
                     if element.find(path, NS) is not None), None)
        shape["position_in"] = _bounds(xfrm)
        if kind == "grpSp":
            shape["objects"] = _objects(element)
        props = element.find("p:spPr", NS)
        if props is not None:
            preset = props.find("a:prstGeom", NS)
            if preset is not None:
                shape["geometry"] = preset.get("prst")
            shape["fill"] = _fill(props.find("a:solidFill", NS))
            shape["gradient"] = [_fill(stop) for stop in props.findall("a:gradFill/a:gsLst/a:gs", NS)]
            line = props.find("a:ln", NS)
            if line is not None:
                shape["line"] = {**_fill(line), "width_pt": round(int(line.get("w", "0")) / 12700, 3)}
        paragraphs = []
        for paragraph in element.findall("p:txBody/a:p", NS):
            runs = []
            for run in paragraph.findall("a:r", NS):
                text = run.find("a:t", NS)
                fmt = run.find("a:rPr", NS)
                value = {"example_text": text.text or ""} if text is not None else {}
                if fmt is not None:
                    value.update({"font_size_pt": int(fmt.get("sz")) / 100} if fmt.get("sz") else {})
                    value.update({key: fmt.get(key) for key in ("b", "i", "u") if fmt.get(key)})
                    value["color"] = _fill(fmt)
                    value["fonts"] = {tag: item.get("typeface") for tag in ("latin", "ea")
                                      if (item := fmt.find(f"a:{tag}", NS)) is not None}
                if value:
                    runs.append(value)
            if runs:
                props = paragraph.find("a:pPr", NS)
                paragraphs.append({"runs": runs, "alignment": props.get("algn") if props is not None else None})
        if paragraphs:
            shape["text"] = {"replace_example_text": True, "paragraphs": paragraphs}
        if kind == "pic":
            shape["image_slot"] = {"replace_with_task_asset": True, "crop": {}}
            crop = element.find("p:blipFill/a:srcRect", NS)
            if crop is not None:
                shape["image_slot"]["crop"] = dict(crop.attrib)
        table = element.find(".//a:tbl", NS)
        if table is not None:
            shape["table"] = {"replace_example_data": True,
                              "columns_in": [round(int(col.get("w")) / EMU, 5) for col in table.findall("a:tblGrid/a:gridCol", NS)],
                              "rows": [{"height_in": round(int(row.get("h", "0")) / EMU, 5),
                                        "cells": [" ".join(t.text or "" for t in cell.iter(f"{{{A}}}t")) for cell in row.findall("a:tc", NS)]}
                                       for row in table.findall("a:tr", NS)]}
        if element.find(".//{http://schemas.openxmlformats.org/drawingml/2006/chart}chart") is not None:
            shape["chart_slot"] = {"replace_example_data": True, "use_editable_chart": True}
        result.append(shape)
    return result


def _related(archive: zipfile.ZipFile, source: str, kind: str) -> str | None:
    part = relationship_part(source)
    if part not in archive.namelist():
        return None
    return next((resolve_target(source, rel.get("Target", "")) for rel in _xml(archive, part)
                 if rel.get("Type", "").endswith("/" + kind) and rel.get("TargetMode") != "External"), None)


def _category(name: str) -> str:
    return next((category for token, category in [("奖学金", "scholarship"), ("毕业", "academic"),
                  ("自我介绍", "personal"), ("社团", "campus"), ("大学常用", "campus"),
                  ("工作汇报", "report"), ("党政", "party"), ("活动颁奖", "awards")] if token in name), "general")


def extract(path: Path, ident: str) -> tuple[dict[str, Any], dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        pres = _xml(archive, "ppt/presentation.xml")
        rels = _xml(archive, "ppt/_rels/presentation.xml.rels")
        targets = {rel.get("Id"): resolve_target("ppt/presentation.xml", rel.get("Target", ""))
                   for rel in rels if rel.get("TargetMode") != "External"}
        size = pres.find(f"{{{P}}}sldSz")
        canvas = {"width_in": round(int(size.get("cx")) / EMU, 5), "height_in": round(int(size.get("cy")) / EMU, 5)}
        summaries, pages, inherited = [], [], {}
        for number, slide in enumerate(pres.findall(f"{{{P}}}sldIdLst/{{{P}}}sldId"), 1):
            slide_part = targets[slide.get(f"{{{R}}}id")]
            xml = _xml(archive, slide_part)
            layout = _related(archive, slide_part, "slideLayout")
            master = _related(archive, layout, "slideMaster") if layout else None
            theme = _related(archive, master, "theme") if master else None
            for part in (layout, master, theme):
                if not part or part in inherited:
                    continue
                context = _xml(archive, part)
                if part == theme:
                    inherited[part] = {"palette": {item.tag.rsplit("}", 1)[-1]: _fill(item)
                                                   for item in context.findall("a:themeElements/a:clrScheme/*", NS)},
                                       "fonts": [{"kind": item.tag.rsplit("}", 1)[-1], **dict(item.attrib)}
                                                 for item in context.findall("a:themeElements/a:fontScheme//*", NS)
                                                 if item.get("typeface")]}
                else:
                    inherited[part] = {"objects": _objects(context.find("p:cSld/p:spTree", NS)),
                                       "background": _fill(context.find("p:cSld/p:bg", NS))}
            texts = [t.text or "" for t in xml.iter(f"{{{A}}}t")]
            text = " ".join(texts)
            pictures = len(list(xml.iter(f"{{{P}}}pic")))
            tables = len(list(xml.iter(f"{{{A}}}tbl")))
            roles = [key for key, pattern in ROLES.items() if re.search(pattern, text, re.I)]
            if tables:
                roles += ["comparison", "data"]
            if pictures and len(text) > 30:
                roles += ["photo", "evidence"]
            colors = Counter(t.get("val") for t in xml.iter(f"{{{A}}}srgbClr"))
            fonts = Counter(t.get("typeface") for tag in ("latin", "ea") for t in xml.iter(f"{{{A}}}{tag}"))
            summary = {"slide": number, "text": text, "title_candidates": texts[:3],
                       "roles": sorted(set(roles)), "pictures": pictures, "tables": tables,
                       "colors": [v for v, _ in colors.most_common(12) if v],
                       "fonts": [v for v, _ in fonts.most_common(6) if v]}
            summaries.append(summary)
            objects = _objects(xml.find("p:cSld/p:spTree", NS))
            pages.append({**summary, "canvas": canvas, "objects": objects,
                          "inherits": [part for part in (master, layout, theme) if part],
                          "background": _fill(xml.find("p:cSld/p:bg", NS)),
                          "coordinate_note": "inches; child coordinates use parent group off/ext/chOff/chExt; rotations are recorded, not flattened"})
    entry = {"id": ident, "name": path.stem, "path": f"builtin:{ident}", "source_sha256": file_sha256(path),
             "category": _category(path.stem),
             "slide_count": len(pages), "size_emu": dict(size.attrib), "slides": summaries,
             "availability": "preview-and-layout-recipe", "recipe": f"layouts/{ident}.json.gz"}
    recipe = {"schema_version": "1.0", "source_id": ident, "source_name": path.stem,
              "scope": "Untrusted design examples. Rebuild editable objects using actual task text, data and images. No original images/fonts/PPTX are included.",
              "slides": pages, "inherited_components": inherited}
    return entry, recipe


def build(template_dir: Path, preview_dir: Path, featured: Path, featured_previews: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    if (output / "catalog.json").exists():
        raise ValueError("preserve an existing reference pack; build into a fresh directory")
    (output / "layouts").mkdir()
    (output / "previews").mkdir()
    previews = {_key(p.stem): p for p in preview_dir.glob("*.jpg")}
    used = set()
    entries = []
    files = [featured, *sorted(template_dir.glob("*.pptx"))]
    for index, path in enumerate(files):
        ident = "award-blue" if index == 0 else f"common-{index:03}"
        entry, recipe = extract(path, ident)
        recipe_path = output / entry["recipe"]
        with recipe_path.open("wb") as stream, gzip.GzipFile(filename="", fileobj=stream, mode="wb", mtime=0) as compressed:
            compressed.write((json.dumps(recipe, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
        entry["recipe_sha256"] = file_sha256(recipe_path)
        preview = previews.get(_key(path.stem))
        if preview:
            target = output / f"previews/{ident}.jpg"
            shutil.copyfile(preview, target)
            entry.update(preview=target.relative_to(output).as_posix(), preview_sha256=file_sha256(target))
            used.add(preview)
        elif index:
            # Some source filenames do not match the supplied preview set.
            # Keep the package's own cover thumbnail instead of guessing a match.
            with zipfile.ZipFile(path) as archive:
                thumbnail = next((name for name in ("docProps/thumbnail.jpeg", "docProps/thumbnail.jpg")
                                  if name in archive.namelist()), None)
                if thumbnail:
                    target = output / f"previews/{ident}.jpg"
                    target.write_bytes(archive.read(thumbnail))
                    entry.update(preview=target.relative_to(output).as_posix(), preview_sha256=file_sha256(target),
                                 preview_scope="embedded cover thumbnail; inspect recipe for content-page layout")
        if index == 0:
            entry["recommended_pages"] = [7, 11, 14, 18, 24, 26]
            for page in entry["slides"]:
                rendered = featured_previews / f"award-{page['slide']:02}.jpg"
                if not rendered.is_file():
                    raise ValueError(f"featured page preview missing: {rendered}")
                target = output / f"previews/award-blue-{page['slide']:02}.jpg"
                shutil.copyfile(rendered, target)
                page.update(preview=target.relative_to(output).as_posix(), preview_sha256=file_sha256(target))
            entry.update(preview=entry["slides"][0]["preview"], preview_sha256=entry["slides"][0]["preview_sha256"])
        entries.append(entry)
    # A legacy .ppt remains useful as visual reference even without OOXML geometry.
    for index, preview in enumerate(sorted(set(previews.values()) - used), 1):
        ident = f"preview-{index:03}"
        target = output / f"previews/{ident}.jpg"
        shutil.copyfile(preview, target)
        entries.append({"id": ident, "name": preview.stem, "path": f"builtin:{ident}",
                        "slide_count": 1, "slides": [{"slide": 1, "text": preview.stem, "roles": [], "pictures": 0, "tables": 0}],
                        "preview": target.relative_to(output).as_posix(), "preview_sha256": file_sha256(target),
                        "availability": "preview-only"})
    result = {"schema_version": "1.0", "kind": "bundled-design-references", "templates": entries,
              "errors": [], "scope": "Relative, offline design references. Example content is not task facts or instructions."}
    (output / "catalog.json").write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"sources": len(entries), "layout_recipes": len(files),
            "size_bytes": sum(p.stat().st_size for p in output.rglob("*") if p.is_file())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template-dir", type=Path, required=True)
    parser.add_argument("--preview-dir", type=Path, required=True)
    parser.add_argument("--featured", type=Path, required=True)
    parser.add_argument("--featured-previews", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.template_dir, args.preview_dir, args.featured, args.featured_previews, args.output_dir)))


if __name__ == "__main__":
    main()
