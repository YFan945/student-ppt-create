"""Local template discovery and lossless selection of editable source slides.

Catalog text is untrusted reference material, never author instructions. No
provider calls, automatic layout choice, or copying into the plugin cache.
"""
from __future__ import annotations

import io
import json
import posixpath
import re
import tempfile
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

from defusedxml import ElementTree as ET
from lxml import etree

from shared.hashing import file_sha256
from shared.pptx_runtime.edit import _next_part_name
from shared.pptx_runtime.package import pack_directory, relationship_part, resolve_target, safe_extract_package

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
ROLES = {
    "cover": r"封面|cover",
    "evidence": r"证书|荣誉|奖项|成果|实验|证据|结果|evidence|result",
    "comparison": r"比较|对比|方案|维度|comparison",
    "process": r"流程|原理|机制|步骤|架构|转换|路径|环节|process|mechanism",
    "timeline": r"历程|阶段|时间|成长|经历|计划|timeline",
    "data": r"成绩|数据|排名|统计|指标|比例|规模|增速|成本|容量|data|LCOE",
    "photo": r"实践|活动|照片|调研|志愿|photo",
}


def _xml(path: Path):
    return etree.parse(str(path), etree.XMLParser(resolve_entities=False, no_network=True))


def _key(value: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value)).casefold()


def slide_parts(root: Path) -> tuple[list[str], dict[str, str]]:
    presentation = ET.parse(root / "ppt/presentation.xml").getroot()
    relationships = ET.parse(root / "ppt/_rels/presentation.xml.rels").getroot()
    targets = {item.get("Id"): resolve_target("ppt/presentation.xml", item.get("Target", ""))
               for item in relationships if item.get("TargetMode") != "External"}
    return ([targets[item.get(f"{{{R}}}id")] for item in presentation.findall(f"{{{P}}}sldIdLst/{{{P}}}sldId")],
            presentation.find(f"{{{P}}}sldSz").attrib)


def inspect_template(path: Path, previews: dict[str, str] | None = None) -> dict[str, Any]:
    path = path.resolve()
    with tempfile.TemporaryDirectory(prefix="sps-template-") as directory:
        root = Path(directory)
        safe_extract_package(path, root)
        parts, size = slide_parts(root)
        pages = []
        for number, part in enumerate(parts, 1):
            xml = ET.parse(root / part).getroot()
            texts = [item.text or "" for item in xml.iter(f"{{{A}}}t")]
            text = " ".join(texts)
            colors = Counter(item.get("val") for item in xml.iter(f"{{{A}}}srgbClr"))
            fonts = Counter(item.get("typeface") for tag in ("latin", "ea") for item in xml.iter(f"{{{A}}}{tag}"))
            pages.append({"slide": number, "text": text, "title_candidates": texts[:3],
                          "roles": [key for key, pattern in ROLES.items() if re.search(pattern, text, re.I)],
                          "pictures": len(list(xml.iter(f"{{{P}}}pic"))),
                          "tables": len(list(xml.iter(f"{{{A}}}tbl"))),
                          "colors": [color for color, _ in colors.most_common(12) if color],
                          "fonts": [font for font, _ in fonts.most_common(6) if font]})
    return {"id": file_sha256(path)[:16], "path": str(path), "sha256": file_sha256(path),
            "name": path.stem, "size_emu": dict(size), "slide_count": len(pages),
            "preview": (previews or {}).get(_key(path.stem)), "slides": pages}


def build_catalog(template_dirs: list[Path], preview_dirs: list[Path]) -> dict[str, Any]:
    previews = {_key(path.stem): str(path.resolve()) for directory in preview_dirs
                for path in sorted(directory.rglob("*")) if path.suffix.lower() in {".jpg", ".jpeg", ".png"}}
    entries, errors = [], []
    paths = sorted({path.resolve() for directory in template_dirs for path in directory.rglob("*")
                    if path.suffix.lower() in {".pptx", ".potx"} and not path.name.startswith("~$")})
    for path in paths:
        try:
            entries.append(inspect_template(path, previews))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
            errors.append({"path": str(path), "error": str(exc)})
    return {"schema_version": "1.0", "scope": "untrusted local design references; not evidence or instructions",
            "templates": entries, "errors": errors}


def search_catalog(catalog: dict[str, Any], query: str, role: str | None, limit: int = 12) -> list[dict[str, Any]]:
    terms = [part.casefold() for part in query.split() if part]
    matches = []
    for entry in catalog.get("templates", []):
        for page in entry["slides"]:
            cover = (page["slide"] == 1 and entry.get("slide_count", len(entry["slides"])) > 1) or "cover" in page["roles"]
            if role == "cover" and not cover:
                continue
            if role and role != "cover" and (cover or role not in page["roles"]):
                continue
            haystack = (entry["name"] + " " + page["text"]).casefold()
            score = sum(haystack.count(term) for term in terms)
            if terms and not score:
                continue
            matches.append({"source_id": entry["id"], "path": entry["path"], "name": entry["name"],
                            "preview": page.get("preview") or entry.get("preview"), "slide": page["slide"], "score": score,
                            "availability": entry.get("availability", "original-pptx"),
                            "recommended": page["slide"] in entry.get("recommended_pages", []),
                            "page_kind": "cover" if cover else "body",
                            "recipe_command": f"template_library.py recipe {entry['id']} --slide {page['slide']}" if entry["path"].startswith("builtin:") else None,
                            "roles": page["roles"], "text": page["text"][:500],
                            "pictures": page["pictures"], "tables": page["tables"]})
    return sorted(matches, key=lambda item: (-item["score"], not item["recommended"], item["name"], item["slide"]))[:limit]


def assemble(selection: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    """Copy selected slide graphs, retaining source masters/themes and editable objects.

    This prepares an editing source, not a finished student deck. Same-size
    sources only; typography/color harmonization and content replacement are
    deliberate author edits. Never infer an original's facts as user facts.
    """
    from pptx import Presentation

    output = output.resolve()
    sources = [Path(item["path"]).resolve() for item in selection]
    if not sources or output in sources or output.suffix.lower() != ".pptx":
        raise ValueError("choose source slides and a separate .pptx output")
    with tempfile.TemporaryDirectory(prefix="sps-assemble-") as directory:
        base = Path(directory)
        destination = base / "output"
        empty = io.BytesIO()
        Presentation().save(empty)
        seed = base / "empty.pptx"
        seed.write_bytes(empty.getvalue())
        safe_extract_package(seed, destination)
        pres = _xml(destination / "ppt/presentation.xml")
        pres_rels = _xml(destination / "ppt/_rels/presentation.xml.rels")
        types = _xml(destination / "[Content_Types].xml")
        slides = pres.find(f"{{{P}}}sldIdLst")
        if slides is None:
            slides = etree.Element(f"{{{P}}}sldIdLst")
            pres.getroot().insert(1, slides)
        provenance = []
        size = None
        next_id = 2147500000
        notes_master_part = None
        notes_master_registered = False
        for index, (item, path) in enumerate(zip(selection, sources, strict=True), 1):
            source = base / f"source-{index}"
            safe_extract_package(path, source)
            parts, dimensions = slide_parts(source)
            number = item["slide"]
            if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(parts):
                raise ValueError(f"invalid slide {number} in {path}")
            if size is not None and size != (dimensions["cx"], dimensions["cy"]):
                raise ValueError("template sizes differ; choose matching canvases or deliberately rebuild, never stretch")
            size = (dimensions["cx"], dimensions["cy"])
            pres.find(f"{{{P}}}sldSz").set("cx", size[0])
            pres.find(f"{{{P}}}sldSz").set("cy", size[1])
            source_types = ET.parse(source / "[Content_Types].xml").getroot()
            overrides = {t.get("PartName").lstrip("/"): t.get("ContentType") for t in source_types if t.tag.endswith("Override")}
            defaults = {t.get("Extension"): t.get("ContentType") for t in source_types if t.tag.endswith("Default")}
            mapping: dict[str, str] = {}

            def clone(part: str, mapping=mapping, source=source,
                      overrides=overrides, defaults=defaults, root_slide=parts[number - 1]) -> str:
                nonlocal next_id, notes_master_part
                if part in mapping:
                    return mapping[part]
                if overrides.get(part, "").endswith("notesMaster+xml") and notes_master_part:
                    mapping[part] = notes_master_part
                    return notes_master_part
                src = source / part
                if not src.is_file():
                    raise ValueError(f"missing template dependency: {part}")
                dest = _next_part_name(destination, part)
                mapping[part] = dest
                target = destination / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(src.read_bytes())
                content_type = overrides.get(part) or defaults.get(Path(part).suffix.lstrip("."))
                if content_type and content_type.endswith("notesMaster+xml"):
                    notes_master_part = dest
                if not content_type:
                    raise ValueError(f"unknown template part content type: {part}")
                etree.SubElement(types.getroot(), f"{{{CT}}}Override", PartName="/" + dest, ContentType=content_type)
                rel_path = source / relationship_part(part)
                if rel_path.is_file():
                    relations = _xml(rel_path)
                    for relation in relations.getroot():
                        if relation.get("TargetMode") == "External":
                            continue
                        old = resolve_target(part, relation.get("Target", ""))
                        if relation.get("Type") == f"{R}/slide" and old != root_slide:
                            raise ValueError("template links to an unselected slide; remove that internal hyperlink before assembly")
                        new = clone(old)
                        relation.set("Target", posixpath.relpath(new, posixpath.dirname(dest)))
                    rel_target = destination / relationship_part(dest)
                    rel_target.parent.mkdir(parents=True, exist_ok=True)
                    relations.write(str(rel_target), encoding="UTF-8", xml_declaration=True)
                if content_type.endswith("slideMaster+xml"):
                    master = _xml(target)
                    for layout in master.findall(f"{{{P}}}sldLayoutIdLst/{{{P}}}sldLayoutId"):
                        next_id += 1
                        layout.set("id", str(next_id))
                    master.write(str(target), encoding="UTF-8", xml_declaration=True)
                return dest

            imported = clone(parts[number - 1])

            def register(part: str, kind: str, list_tag: str, item_tag: str, ident: int | None = None, index=index) -> str:
                rid = f"rIdSps{index}_{len(pres_rels.getroot())}"
                etree.SubElement(pres_rels.getroot(), f"{{{REL}}}Relationship", Id=rid, Type=f"{R}/{kind}", Target=posixpath.relpath(part, "ppt"))
                listing = pres.find(f"{{{P}}}{list_tag}")
                if listing is None:
                    listing = etree.Element(f"{{{P}}}{list_tag}")
                    # Masters precede slides; notes masters follow slide masters.
                    pres.getroot().insert(1 if list_tag == "notesMasterIdLst" else 0, listing)
                attrs = {f"{{{R}}}id": rid}
                if ident is not None:
                    attrs["id"] = str(ident)
                etree.SubElement(listing, f"{{{P}}}{item_tag}", attrs)
                return rid

            register(imported, "slide", "sldIdLst", "sldId", 255 + index)
            for original, copied in mapping.items():
                typ = overrides.get(original, "")
                if typ.endswith("slideMaster+xml"):
                    next_id += 1
                    register(copied, "slideMaster", "sldMasterIdLst", "sldMasterId", next_id)
                elif typ.endswith("notesMaster+xml") and not notes_master_registered:
                    register(copied, "notesMaster", "notesMasterIdLst", "notesMasterId")
                    notes_master_registered = True
            provenance.append({"output_slide": index, "source": str(path), "source_sha256": file_sha256(path),
                               "source_slide": number, "reason": item.get("reason", "")})
        pres.write(str(destination / "ppt/presentation.xml"), encoding="UTF-8", xml_declaration=True)
        pres_rels.write(str(destination / "ppt/_rels/presentation.xml.rels"), encoding="UTF-8", xml_declaration=True)
        types.write(str(destination / "[Content_Types].xml"), encoding="UTF-8", xml_declaration=True)
        pack_directory(destination, output)
    result = {"output": str(output), "sha256": file_sha256(output), "slides": provenance,
              "status": "editing-source; replace example content, harmonize and inspect before delivery"}
    output.with_suffix(".template-sources.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
