"""PPTX slide-structure editing and orphan cleanup."""

from __future__ import annotations

import posixpath
import re
import shutil
import tempfile
from collections import deque
from pathlib import Path, PurePosixPath

from defusedxml import ElementTree as ET

from .package import relationship_part, resolve_target

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
SLIDE_REL = f"{OFFICE_REL_NS}/slide"
LAYOUT_REL = f"{OFFICE_REL_NS}/slideLayout"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"


def _layout_placeholder_xml(layout_path: Path) -> list[str]:
    """Return ``<p:sp>`` placeholder stubs mirroring the referenced slide layout.

    A slide inherits a layout placeholder (title/body/…) by declaring an empty
    ``<p:sp>`` whose ``<p:ph>`` matches the layout's type/idx. Without these the
    new slide renders blank.
    """
    stubs: list[str] = []
    try:
        root = ET.parse(layout_path).getroot()
    except (OSError, ET.ParseError):
        return stubs
    sp_id = 2
    for sp in root.iter(f"{{{P_NS}}}sp"):
        ph = sp.find(f"{{{P_NS}}}nvSpPr/{{{P_NS}}}nvPr/{{{P_NS}}}ph")
        if ph is None:
            continue
        ph_type = ph.attrib.get("type", "")
        ph_idx = ph.attrib.get("idx", "")
        attrs = f' type="{ph_type}"' if ph_type else ""
        if ph_idx:
            attrs += f' idx="{ph_idx}"'
        stubs.append(
            f'<p:sp><p:nvSpPr><p:cNvPr id="{sp_id}" name="{ph_type or "placeholder"}"/>'
            f"<p:cNvSpPr/><p:nvPr><p:ph{attrs}/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>"
        )
        sp_id += 1
    return stubs
CLONED_REL_TYPES = {
    f"{OFFICE_REL_NS}/notesSlide",
    f"{OFFICE_REL_NS}/comments",
    f"{OFFICE_REL_NS}/chart",
    f"{OFFICE_REL_NS}/diagramData",
    f"{OFFICE_REL_NS}/diagramLayout",
    f"{OFFICE_REL_NS}/diagramQuickStyle",
    f"{OFFICE_REL_NS}/diagramColors",
    f"{OFFICE_REL_NS}/package",
    f"{OFFICE_REL_NS}/oleObject",
    "http://schemas.microsoft.com/office/2018/10/relationships/comments",
    "http://schemas.microsoft.com/office/2014/relationships/chartEx",
    "http://schemas.microsoft.com/office/2011/relationships/chartStyle",
    "http://schemas.microsoft.com/office/2011/relationships/chartColorStyle",
    "http://schemas.microsoft.com/office/2016/relationships/chartDrawing",
}
SLIDE_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"


def _insert_before_close(path: Path, closing: str, fragment: str) -> None:
    text = path.read_text(encoding="utf-8")
    if closing not in text:
        raise ValueError(f"missing {closing} in {path}")
    path.write_text(text.replace(closing, fragment + closing, 1), encoding="utf-8")


def _next_slide_name(root: Path) -> str:
    numbers = []
    for path in (root / "ppt" / "slides").glob("slide*.xml"):
        match = re.fullmatch(r"slide(\d+)\.xml", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return f"slide{max(numbers, default=0) + 1}.xml"


def _next_rid(text: str) -> str:
    values = [int(value) for value in re.findall(r'\bId=["\']rId(\d+)["\']', text)]
    return f"rId{max(values, default=0) + 1}"


def _next_slide_id(text: str) -> int:
    values = [int(value) for value in re.findall(r'<p:sldId\b[^>]*\bid=["\'](\d+)["\']', text)]
    return max([255, *values]) + 1


def _slide_rid_for_name(rels_text: str, slide_name: str) -> str | None:
    return next(
        (rid for rid, registered_name in _slide_relationships(rels_text).items() if registered_name == slide_name),
        None,
    )


def _append_slide_id(presentation: Path, rid: str, after_rid: str | None) -> None:
    text = presentation.read_text(encoding="utf-8")
    fragment = f'<p:sldId id="{_next_slide_id(text)}" r:id="{rid}"/>'
    if after_rid:
        match = re.search(rf'<p:sldId\b[^>]*\br:id="{re.escape(after_rid)}"[^>]*/>', text)
        if not match:
            raise ValueError(f"cannot find insertion slide relationship: {after_rid}")
        text = text[: match.end()] + fragment + text[match.end() :]
    elif "</p:sldIdLst>" in text:
        text = text.replace("</p:sldIdLst>", fragment + "</p:sldIdLst>", 1)
    elif re.search(r"<p:sldIdLst\s*/>", text):
        text = re.sub(r"<p:sldIdLst\s*/>", f"<p:sldIdLst>{fragment}</p:sldIdLst>", text, count=1)
    elif "</p:sldMasterIdLst>" in text:
        text = text.replace(
            "</p:sldMasterIdLst>",
            f"</p:sldMasterIdLst><p:sldIdLst>{fragment}</p:sldIdLst>",
            1,
        )
    else:
        raise ValueError("presentation.xml has no slide list insertion point")
    presentation.write_text(text, encoding="utf-8")


def _register_content_type(root: Path, slide_name: str) -> None:
    path = root / "[Content_Types].xml"
    text = path.read_text(encoding="utf-8")
    part = f"/ppt/slides/{slide_name}"
    if f'PartName="{part}"' not in text:
        _insert_before_close(
            path,
            "</Types>",
            f'<Override PartName="{part}" ContentType="{SLIDE_CONTENT_TYPE}"/>',
        )


def _next_part_name(root: Path, source: str) -> str:
    part = PurePosixPath(source)
    match = re.fullmatch(r"(.*?)(\d+)?", part.stem)
    base = match.group(1) if match else part.stem
    index = 1
    while True:
        index += 1
        candidate = (part.parent / f"{base}{index}{part.suffix}").as_posix()
        if not (root / Path(candidate)).exists():
            return candidate


def _register_cloned_content_type(root: Path, source: str, destination: str) -> None:
    path = root / "[Content_Types].xml"
    text = path.read_text(encoding="utf-8")
    match = re.search(
        rf'<Override\b(?=[^>]*\bPartName=["\']/{re.escape(source)}["\'])[^>]*/>',
        text,
    )
    if match and f'PartName="/{destination}"' not in text and f"PartName='/{destination}'" not in text:
        clone = re.sub(
            r'\bPartName=(["\'])/[^"\']+\1',
            f'PartName="/{destination}"',
            match.group(0),
            count=1,
        )
        _insert_before_close(path, "</Types>", clone)


def _clone_part_graph(
    root: Path,
    source: str,
    cloned: dict[str, str],
) -> str:
    if source in cloned:
        return cloned[source]
    source_path = root / Path(source)
    if not source_path.is_file():
        raise ValueError(f"cannot clone missing related part: {source}")
    destination = _next_part_name(root, source)
    cloned[source] = destination
    destination_path = root / Path(destination)
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination_path)
    _register_cloned_content_type(root, source, destination)

    source_rels_name = relationship_part(source)
    source_rels = root / Path(source_rels_name)
    if not source_rels.is_file():
        return destination
    destination_rels = root / Path(relationship_part(destination))
    destination_rels.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.parse(source_rels)
    rels_root = tree.getroot()
    for relation in rels_root:
        if relation.attrib.get("TargetMode") == "External":
            continue
        relation_type = relation.attrib.get("Type", "")
        target = relation.attrib.get("Target")
        if relation_type not in CLONED_REL_TYPES or not target:
            continue
        target_source = resolve_target(source, target)
        target_destination = _clone_part_graph(root, target_source, cloned)
        relation.attrib["Target"] = posixpath.relpath(
            target_destination,
            posixpath.dirname(destination),
        )
    tree.write(destination_rels, encoding="utf-8", xml_declaration=True)
    return destination


def _retarget_relationship(root: Path, source: str, relation_type: str, target: str) -> None:
    rels = root / Path(relationship_part(source))
    if not rels.is_file():
        raise ValueError(f"cloned part has no relationships: {source}")
    tree = ET.parse(rels)
    matches = [
        relation
        for relation in tree.getroot()
        if relation.attrib.get("Type") == relation_type
        and relation.attrib.get("TargetMode") != "External"
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected one {relation_type} relationship in {source}, found {len(matches)}"
        )
    matches[0].attrib["Target"] = posixpath.relpath(target, posixpath.dirname(source))
    tree.write(rels, encoding="utf-8", xml_declaration=True)


def _copy_slide_relationships(
    root: Path,
    source_slide: str,
    destination_slide: str,
) -> None:
    """Copy slide relationships and clone mutable slide-owned dependency graphs."""
    source_rels = root / Path(relationship_part(source_slide))
    destination_rels = root / Path(relationship_part(destination_slide))
    tree = ET.parse(source_rels)
    cloned: dict[str, str] = {}
    for relation in tree.getroot():
        if relation.attrib.get("TargetMode") == "External":
            continue
        relation_type = relation.attrib.get("Type", "")
        target = relation.attrib.get("Target")
        if relation_type not in CLONED_REL_TYPES or not target:
            continue
        source_target = resolve_target(source_slide, target)
        destination_target = _clone_part_graph(root, source_target, cloned)
        if relation_type == f"{OFFICE_REL_NS}/notesSlide":
            _retarget_relationship(
                root,
                destination_target,
                SLIDE_REL,
                destination_slide,
            )
        relation.attrib["Target"] = posixpath.relpath(
            destination_target,
            posixpath.dirname(destination_slide),
        )
    destination_rels.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination_rels, encoding="utf-8", xml_declaration=True)


def add_slide(root: Path, source: str, after: str | None = None) -> str:
    slides = root / "ppt" / "slides"
    layouts = root / "ppt" / "slideLayouts"
    presentation = root / "ppt" / "presentation.xml"
    presentation_rels = root / "ppt" / "_rels" / "presentation.xml.rels"
    new_name = _next_slide_name(root)
    destination = slides / new_name
    source_path = slides / source
    rels_text = presentation_rels.read_text(encoding="utf-8")
    after_rid = _slide_rid_for_name(rels_text, after) if after else None
    if after and not after_rid:
        raise ValueError(f"cannot find --after slide: {after}")

    if source_path.is_file():
        shutil.copy2(source_path, destination)
        source_rels = slides / "_rels" / f"{source}.rels"
        if source_rels.is_file():
            _copy_slide_relationships(
                root,
                f"ppt/slides/{source}",
                f"ppt/slides/{new_name}",
            )
    else:
        layout = layouts / source
        if not layout.is_file() or not re.fullmatch(r"slideLayout\d+\.xml", source):
            raise ValueError(f"source must be an existing slideN.xml or slideLayoutN.xml: {source}")
        ph_stubs = _layout_placeholder_xml(layout)
        sp_tree = (
            '<p:nvGrpSpPr><p:cNvPr id="1" name=""/>'
            '<p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr><p:grpSpPr/>'
            + "".join(ph_stubs)
        )
        destination.write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
            'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            f'<p:cSld><p:spTree>{sp_tree}</p:spTree></p:cSld>'
            '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>',
            encoding="utf-8",
        )
        rels_path = slides / "_rels" / f"{new_name}.rels"
        rels_path.parent.mkdir(parents=True, exist_ok=True)
        rels_path.write_text(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" Type="{LAYOUT_REL}" '
            f'Target="../slideLayouts/{source}"/></Relationships>',
            encoding="utf-8",
        )

    rid = _next_rid(rels_text)
    _insert_before_close(
        presentation_rels,
        "</Relationships>",
        f'<Relationship Id="{rid}" Type="{SLIDE_REL}" Target="slides/{new_name}"/>',
    )
    _append_slide_id(presentation, rid, after_rid)
    _register_content_type(root, new_name)
    return new_name


def _slide_relationships(rels_text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for tag in re.findall(r"<Relationship\b[^>]*/>", rels_text):
        if SLIDE_REL not in tag:
            continue
        rid = re.search(r'\bId=["\']([^"\']+)["\']', tag)
        target = re.search(
            r'\bTarget=["\'](?:/ppt/)?slides/([^"\']+)["\']',
            tag,
        )
        if rid and target:
            result[rid.group(1)] = target.group(1)
    return result


def _slide_id_tags(presentation_text: str) -> list[tuple[str, str]]:
    result = []
    for tag in re.findall(r"<p:sldId\b[^>]*/>", presentation_text):
        rid = re.search(r'\br:id=["\']([^"\']+)["\']', tag)
        if rid:
            result.append((rid.group(1), tag))
    return result


_SLIDE_PART_NAME = re.compile(r"^slide[1-9][0-9]*\.xml$")


def _contained_slide_part(root: Path, slide_name: str) -> Path:
    """A real slide part under ppt/slides, never a relationship target that escapes."""
    if not _SLIDE_PART_NAME.fullmatch(slide_name):
        raise ValueError(f"slide name must be a ppt/slides/slideN.xml part: {slide_name}")
    slides = (root / "ppt" / "slides").resolve()
    slide = slides / slide_name
    if slide.resolve().parent != slides:
        raise ValueError(f"slide part resolves outside ppt/slides: {slide_name}")
    rels = slides / "_rels" / f"{slide_name}.rels"
    if rels.exists() or rels.is_symlink():
        rels_dir = (slides / "_rels").resolve()
        if rels.resolve().parent != rels_dir:
            raise ValueError(f"slide relationships resolve outside ppt/slides: {slide_name}")
    return slide


def delete_slide(root: Path, slide_name: str) -> None:
    slide = _contained_slide_part(root, slide_name)
    presentation = root / "ppt" / "presentation.xml"
    presentation_rels = root / "ppt" / "_rels" / "presentation.xml.rels"
    presentation_text = presentation.read_text(encoding="utf-8")
    rels_text = presentation_rels.read_text(encoding="utf-8")
    slide_relations = _slide_relationships(rels_text)
    rid = next((key for key, value in slide_relations.items() if value == slide_name), None)
    if rid is None:
        raise ValueError(f"slide is not registered in the presentation: {slide_name}")
    slide_tags = _slide_id_tags(presentation_text)
    if len(slide_tags) <= 1:
        raise ValueError("cannot delete the final slide")
    presentation_text, removed_ids = re.subn(
        rf'<p:sldId\b(?=[^>]*\br:id=["\']{re.escape(rid)}["\'])[^>]*/>',
        "",
        presentation_text,
        count=1,
    )
    rels_text, removed_rels = re.subn(
        rf'<Relationship\b(?=[^>]*\bId=["\']{re.escape(rid)}["\'])[^>]*/>',
        "",
        rels_text,
        count=1,
    )
    if removed_ids != 1 or removed_rels != 1:
        raise ValueError(f"could not remove slide registration cleanly: {slide_name}")
    presentation.write_text(presentation_text, encoding="utf-8")
    presentation_rels.write_text(rels_text, encoding="utf-8")
    slide_rels = slide.parent / "_rels" / f"{slide_name}.rels"
    if slide.is_file() or slide.is_symlink():
        slide.unlink()
    if slide_rels.is_file() or slide_rels.is_symlink():
        slide_rels.unlink()
    content_types = root / "[Content_Types].xml"
    types_text = content_types.read_text(encoding="utf-8")
    types_text = re.sub(
        rf'<Override\b(?=[^>]*\bPartName=["\']/ppt/slides/{re.escape(slide_name)}["\'])[^>]*/>',
        "",
        types_text,
    )
    content_types.write_text(types_text, encoding="utf-8")


def reorder_slides(root: Path, slide_names: list[str]) -> None:
    presentation = root / "ppt" / "presentation.xml"
    presentation_rels = root / "ppt" / "_rels" / "presentation.xml.rels"
    presentation_text = presentation.read_text(encoding="utf-8")
    slide_relations = _slide_relationships(presentation_rels.read_text(encoding="utf-8"))
    current_tags = _slide_id_tags(presentation_text)
    current_names = [slide_relations.get(rid) for rid, _tag in current_tags]
    if len(slide_names) != len(set(slide_names)):
        raise ValueError("reorder list contains duplicate slide names")
    if set(slide_names) != set(current_names) or None in current_names:
        raise ValueError(
            "reorder list must contain every registered slide exactly once: "
            + ", ".join(str(name) for name in current_names)
        )
    tag_by_name = {
        slide_relations[rid]: tag
        for rid, tag in current_tags
    }
    replacement = "".join(tag_by_name[name] for name in slide_names)
    presentation_text, count = re.subn(
        r"(<p:sldIdLst\b[^>]*>).*?(</p:sldIdLst>)",
        rf"\1{replacement}\2",
        presentation_text,
        count=1,
        flags=re.DOTALL,
    )
    if count != 1:
        raise ValueError("presentation.xml has no reorderable slide list")
    presentation.write_text(presentation_text, encoding="utf-8")


def _relationships(path: Path, source: str | None) -> list[str]:
    root = ET.parse(path).getroot()
    targets = []
    for rel in root:
        if rel.attrib.get("TargetMode") == "External":
            continue
        target = rel.attrib.get("Target")
        if target:
            targets.append(resolve_target(source, target))
    return targets


def clean_package(root: Path) -> list[str]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"clean input must be an unpacked package directory: {root}")
    required = {
        "[Content_Types].xml",
        "_rels/.rels",
        "ppt/presentation.xml",
        "ppt/_rels/presentation.xml.rels",
    }
    all_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    missing_required = sorted(required - all_files)
    if missing_required:
        raise ValueError("refusing to clean package with missing roots: " + ", ".join(missing_required))
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("refusing to clean an unpacked package containing symbolic links")
    presentation = ET.parse(root / "ppt/presentation.xml").getroot()
    presentation_rels = ET.parse(root / "ppt/_rels/presentation.xml.rels").getroot()
    slide_targets = {
        relation.attrib.get("Id", ""): resolve_target(
            "ppt/presentation.xml", relation.attrib.get("Target", "")
        )
        for relation in presentation_rels
        if relation.attrib.get("Type") == SLIDE_REL and relation.attrib.get("Target")
    }
    registered_rids = [
        slide.attrib.get(f"{{{OFFICE_REL_NS}}}id", "")
        for slide in presentation.iter()
        if slide.tag.rsplit("}", 1)[-1] == "sldId"
    ]
    if not registered_rids:
        raise ValueError("refusing to clean a presentation with no registered slides")
    unresolved_slides = [rid for rid in registered_rids if rid not in slide_targets]
    if unresolved_slides:
        raise ValueError(
            "refusing to clean presentation with unresolved slide registrations: "
            + ", ".join(unresolved_slides)
        )
    keep = {"[Content_Types].xml", "_rels/.rels"}
    queue: deque[str | None] = deque([None])
    seen_sources: set[str | None] = set()
    while queue:
        source = queue.popleft()
        if source in seen_sources:
            continue
        seen_sources.add(source)
        rels = "_rels/.rels" if source is None else relationship_part(source)
        if rels not in all_files:
            continue
        keep.add(rels)
        for target in _relationships(root / Path(rels), source):
            if target not in all_files:
                raise ValueError(f"refusing to clean package with dangling relationship: {rels} -> {target}")
            if target not in keep:
                keep.add(target)
                queue.append(target)
    if "ppt/presentation.xml" not in keep:
        raise ValueError("refusing to clean package whose presentation is unreachable from _rels/.rels")
    removed = sorted(all_files - keep)
    if not removed:
        return []

    content_types = root / "[Content_Types].xml"
    original_types = content_types.read_bytes()
    types_text = original_types.decode("utf-8")
    for name in removed:
        types_text = re.sub(
            rf'<Override\b(?=[^>]*\bPartName=["\']/{re.escape(name)}["\'])[^>]*/>',
            "",
            types_text,
        )
    moved: list[tuple[Path, Path]] = []
    temporary_types = content_types.with_name("[Content_Types].xml.clean-tmp")
    trash = Path(tempfile.mkdtemp(prefix="pptx-clean-", dir=root.parent))
    try:
        for name in removed:
            source_path = root / Path(name)
            trash_path = trash / Path(name)
            trash_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source_path), str(trash_path))
            moved.append((source_path, trash_path))
        temporary_types.write_text(types_text, encoding="utf-8")
        temporary_types.replace(content_types)
    except Exception:
        if temporary_types.exists():
            temporary_types.unlink()
        content_types.write_bytes(original_types)
        for source_path, trash_path in reversed(moved):
            if trash_path.exists():
                source_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(trash_path), str(source_path))
        shutil.rmtree(trash, ignore_errors=True)
        raise
    shutil.rmtree(trash, ignore_errors=True)
    for directory in sorted((path for path in root.rglob("*") if path.is_dir()), reverse=True):
        if not any(directory.iterdir()):
            directory.rmdir()
    return removed
