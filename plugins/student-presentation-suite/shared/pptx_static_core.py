"""Shared static PPTX XML risk checks.

The checks are intentionally conservative: they flag likely readability and
layout risks from PPTX XML, but rendered previews remain the source of truth.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
    "c": "http://schemas.openxmlformats.org/drawingml/2006/chart",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}

EMU_PER_CM = 360_000
SMALL_TEXT_BOX_WIDTH_EMU = 900_000
SMALL_TEXT_BOX_HEIGHT_EMU = 250_000
TEXT_CHARS_PER_CM_LIMIT = 18
CHINESE_PARAGRAPH_LIMIT = 160
LATIN_PARAGRAPH_LIMIT = 220

# 垂直溢出预估常量（基于 22pt 中文 / 20pt 英文的最小字号约束）
CJK_CHAR_WIDTH_RATIO = 0.035   # 中文字宽 ≈ 字号 × 0.035cm
LATIN_CHAR_WIDTH_RATIO = 0.021  # 英文平均字宽 ≈ 字号 × 0.021cm
LINE_HEIGHT_RATIO = 1.4          # 行高 ≈ 字号 × 1.4
OVERFLOW_BOX_FILL_RATIO = 0.85   # 文字总高超过盒高 85% 时判定溢出风险
HEADING_PLACEHOLDER_TYPES = {"title", "ctrTitle", "subTitle"}
PRIMARY_TITLE_PLACEHOLDER_TYPES = {"title", "ctrTitle"}
BODY_PLACEHOLDER_TYPES = {"body", "dt", "ftr", "sldNum"}
HEADING_NAME_HINTS = ("title", "subtitle", "heading", "header", "标题", "副标题")
DEFAULT_MAX_PPTX_BYTES = 80 * 1024 * 1024
# 画布事实标准在 JS 侧（pptx-helpers.js SLIDE_W_IN/SLIDE_H_IN = 10×5.625in，
# applyTokens 以 STUDENT_WIDE 版式写盘）；这里的默认值只是 presentation.xml
# 缺失 sldSz 时的兜底，必须与 JS 产物一致，否则静态分析会按错误画布判断越界。
# tests/test_stack_contract.py 锁定两侧一致。
DEFAULT_SLIDE_WIDTH_EMU = 9_144_000
DEFAULT_SLIDE_HEIGHT_EMU = 5_143_500
EDGE_MARGIN_EMU = 72_000
MIN_UNINTENDED_OVERLAP_EMU = 72_000
ALIGNMENT_TOLERANCE_EMU = 38_100  # 3pt
MIN_GUTTER_EMU = 228_600  # 18pt
MIN_CARD_PADDING_EMU = 203_200  # 16pt
PORTABLE_FONT_FAMILIES = {
    "arial",
    "calibri",
    "aptos",
    "aptos display",
    "times new roman",
    "microsoft yahei",
    "微软雅黑",
    "simsun",
    "宋体",
    "noto sans cjk sc",
    "noto serif cjk sc",
    "georgia",
}


def text_of(el: ET.Element) -> str:
    parts = []
    for t in el.findall(".//a:t", NS):
        if t.text:
            parts.append(t.text)
    return "".join(parts).strip()


def pptx_size_to_pt(sz: str | None) -> float | None:
    if sz and sz.isdigit():
        return int(sz) / 100
    return None


def font_sizes(el: ET.Element) -> list[float]:
    sizes: list[float] = []
    for paragraph in el.findall(".//a:p", NS):
        default_size = None
        def_rpr = paragraph.find("./a:pPr/a:defRPr", NS)
        if def_rpr is not None:
            default_size = pptx_size_to_pt(def_rpr.attrib.get("sz"))
        for run in paragraph.findall("./a:r", NS):
            run_size = None
            rpr = run.find("./a:rPr", NS)
            if rpr is not None:
                run_size = pptx_size_to_pt(rpr.attrib.get("sz"))
            effective_size = run_size if run_size is not None else default_size
            if effective_size is not None:
                sizes.append(effective_size)
    return sizes


def rels_path(part_name: str) -> str:
    directory, filename = posixpath.split(part_name)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def resolve_relationship_target(source_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def relationship_target(zf: zipfile.ZipFile, source_part: str, type_suffix: str) -> str | None:
    rels_name = rels_path(source_part)
    if rels_name not in zf.namelist():
        return None
    root = ET.fromstring(zf.read(rels_name))
    for rel in root.findall("./rel:Relationship", NS):
        rel_type = rel.attrib.get("Type", "")
        target = rel.attrib.get("Target")
        if target and rel_type.endswith(type_suffix):
            return resolve_relationship_target(source_part, target)
    return None


def relationship_id_target(zf: zipfile.ZipFile, source_part: str, rel_id: str | None) -> str | None:
    if not rel_id:
        return None
    rels_name = rels_path(source_part)
    if rels_name not in zf.namelist():
        return None
    root = ET.fromstring(zf.read(rels_name))
    for rel in root.findall("./rel:Relationship", NS):
        if rel.attrib.get("Id") == rel_id and rel.attrib.get("Target"):
            return resolve_relationship_target(source_part, rel.attrib["Target"])
    return None


def picture_resolution(zf: zipfile.ZipFile, slide_name: str, picture: ET.Element) -> tuple[int, int] | None:
    blip = picture.find(".//a:blip", NS)
    media = relationship_id_target(zf, slide_name, blip.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed") if blip is not None else None)
    if not media or media not in zf.namelist():
        return None
    try:
        from io import BytesIO  # noqa: PLC0415

        from PIL import Image  # noqa: PLC0415
        with Image.open(BytesIO(zf.read(media))) as image:
            return image.size
    except (ImportError, OSError, ValueError):
        return None


def chart_part(zf: zipfile.ZipFile, slide_name: str, frame: ET.Element) -> str | None:
    chart = frame.find(".//c:chart", NS)
    return relationship_id_target(zf, slide_name, chart.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") if chart is not None else None)


def read_xml(zf: zipfile.ZipFile, part_name: str | None) -> ET.Element | None:
    if not part_name or part_name not in zf.namelist():
        return None
    return ET.fromstring(zf.read(part_name))


def first_style_size(root: ET.Element | None, style_name: str) -> float | None:
    if root is None:
        return None
    paths = [
        f".//p:txStyles/a:{style_name}/a:lvl1pPr/a:defRPr",
        f".//p:txStyles/a:{style_name}/a:defRPr",
        ".//p:defaultTextStyle/a:lvl1pPr/a:defRPr",
    ]
    for path in paths:
        node = root.find(path, NS)
        if node is not None:
            size = pptx_size_to_pt(node.attrib.get("sz"))
            if size is not None:
                return size
    return None


def placeholder_type(el: ET.Element) -> str | None:
    ph = el.find("./p:nvSpPr/p:nvPr/p:ph", NS)
    if ph is None:
        return None
    return ph.attrib.get("type") or "body"


def placeholder_font_sizes(root: ET.Element | None) -> dict[str, float]:
    if root is None:
        return {}
    sizes: dict[str, float] = {}
    for shape in root.findall(".//p:sp", NS):
        ph_type = placeholder_type(shape)
        if not ph_type:
            continue
        shape_sizes = font_sizes(shape)
        if shape_sizes:
            sizes.setdefault(ph_type, min(shape_sizes))
    return sizes


def inherited_font_context_for_layout(
    zf: zipfile.ZipFile, layout_name: str | None
) -> dict[str, dict[str, float] | dict[str, str]]:
    master_name = relationship_target(zf, layout_name, "/slideMaster") if layout_name else None
    layout_root = read_xml(zf, layout_name)
    master_root = read_xml(zf, master_name)

    styles: dict[str, float] = {}
    style_sources: dict[str, str] = {}
    for key, style_name in (("title", "titleStyle"), ("body", "bodyStyle"), ("other", "otherStyle")):
        for source, root in (("layout-style", layout_root), ("master-style", master_root)):
            size = first_style_size(root, style_name)
            if size is not None:
                styles[key] = size
                style_sources[key] = source
                break

    placeholders = placeholder_font_sizes(master_root)
    placeholder_sources = {key: "master-placeholder" for key in placeholders}
    layout_placeholders = placeholder_font_sizes(layout_root)
    placeholders.update(layout_placeholders)
    placeholder_sources.update({key: "layout-placeholder" for key in layout_placeholders})
    return {
        "styles": styles,
        "style_sources": style_sources,
        "placeholders": placeholders,
        "placeholder_sources": placeholder_sources,
    }


def inherited_font_sizes(
    el: ET.Element, context: dict[str, dict[str, float] | dict[str, str]], heading: bool
) -> tuple[list[float], str | None]:
    ph_type = placeholder_type(el)
    placeholders = context.get("placeholders", {})
    placeholder_sources = context.get("placeholder_sources", {})
    styles = context.get("styles", {})
    style_sources = context.get("style_sources", {})
    if ph_type and ph_type in placeholders:
        return [placeholders[ph_type]], placeholder_sources.get(ph_type, "placeholder")
    if ph_type in HEADING_PLACEHOLDER_TYPES or heading:
        style_key = "title" if styles.get("title") is not None else "other"
    elif ph_type in BODY_PLACEHOLDER_TYPES:
        style_key = "body" if styles.get("body") is not None else "other"
    else:
        style_key = "other" if styles.get("other") is not None else "body"
    size = styles.get(style_key)
    source = style_sources.get(style_key)
    return ([size], source) if size is not None else ([], None)


def shape_bounds(el: ET.Element) -> dict[str, int] | None:
    transform = el.find(".//a:xfrm", NS)
    if transform is None:
        transform = el.find(".//p:xfrm", NS)
    off = transform.find("./a:off", NS) if transform is not None else None
    ext = transform.find("./a:ext", NS) if transform is not None else None
    if off is None or ext is None:
        return None
    try:
        return {
            "x": int(off.attrib.get("x", "0")),
            "y": int(off.attrib.get("y", "0")),
            "cx": int(ext.attrib.get("cx", "0")),
            "cy": int(ext.attrib.get("cy", "0")),
        }
    except ValueError:
        return None


def is_heading_shape(el: ET.Element) -> bool:
    ph = el.find("./p:nvSpPr/p:nvPr/p:ph", NS)
    if ph is not None and ph.attrib.get("type") in HEADING_PLACEHOLDER_TYPES:
        return True
    c_nv_pr = el.find("./p:nvSpPr/p:cNvPr", NS)
    name = (c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else "").lower()
    return any(hint.lower() in name for hint in HEADING_NAME_HINTS)


def is_primary_title_shape(el: ET.Element) -> bool:
    ph = el.find(".//p:nvPr/p:ph", NS)
    if ph is not None:
        return ph.attrib.get("type") in PRIMARY_TITLE_PLACEHOLDER_TYPES
    c_nv_pr = el.find(".//p:cNvPr", NS)
    name = (c_nv_pr.attrib.get("name", "") if c_nv_pr is not None else "").lower()
    return "title" in name and "subtitle" not in name and "副标题" not in name


def fill_colors(el: ET.Element) -> list[str]:
    colors = []
    for srgb in el.findall(".//a:srgbClr", NS):
        val = srgb.attrib.get("val")
        if val:
            colors.append(f"srgb:{val.upper()}")
    for scheme in el.findall(".//a:schemeClr", NS):
        val = scheme.attrib.get("val")
        if val:
            colors.append(f"scheme:{val}")
    for sys_color in el.findall(".//a:sysClr", NS):
        val = sys_color.attrib.get("val") or sys_color.attrib.get("lastClr")
        if val:
            colors.append(f"sys:{val.upper()}")
    return colors


def _srgb_from_node(node: ET.Element | None) -> str | None:
    if node is None:
        return None
    color = node.find(".//a:srgbClr", NS)
    return color.attrib.get("val", "").upper() if color is not None else None


def solid_fill_color(el: ET.Element) -> str | None:
    fill = el.find("./p:spPr/a:solidFill", NS)
    if fill is None:
        fill = el.find("./p:spPr/a:noFill", NS)
    return _srgb_from_node(fill)


def text_colors(el: ET.Element) -> list[str]:
    colors = []
    for rpr in el.findall(".//a:rPr", NS):
        color = _srgb_from_node(rpr)
        if color:
            colors.append(color)
    return colors


def relative_luminance(color: str) -> float:
    if not _is_valid_hex_color(color):
        return 0.0
    channels = [int(color[index:index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _is_valid_hex_color(color: str) -> bool:
    return len(color) == 6 and all(c in "0123456789ABCDEFabcdef" for c in color)


def contrast_ratio(first: str, second: str) -> float:
    high, low = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def font_families(el: ET.Element) -> list[str]:
    names = []
    for tag in ("latin", "ea", "cs"):
        for node in el.findall(f".//a:{tag}", NS):
            typeface = node.attrib.get("typeface")
            if typeface and not typeface.startswith("+") and typeface not in names:
                names.append(typeface)
    return names


def has_cjk(text: str) -> bool:
    for ch in text:
        cp = ord(ch)
        if (
            0x4E00 <= cp <= 0x9FFF      # CJK Unified Ideographs (Chinese, Japanese, Korean hanzi/kanji/hanja)
            or 0x3400 <= cp <= 0x4DBF   # CJK Extension A
            or 0x3000 <= cp <= 0x303F   # CJK Symbols & Punctuation
            or 0xFF00 <= cp <= 0xFFEF   # Halfwidth/Fullwidth Forms
            or 0x3040 <= cp <= 0x309F   # Hiragana (Japanese)
            or 0x30A0 <= cp <= 0x30FF   # Katakana (Japanese)
            or 0xAC00 <= cp <= 0xD7AF   # Hangul Syllables (Korean)
        ):
            return True
    return False


def estimate_text_overflow(
    chars: int,
    is_cjk: bool,
    font_size_pt: float | None,
    box_width_emu: int,
    box_height_emu: int,
    *,
    paragraphs: list[str] | None = None,
    horizontal_margin_emu: int = 0,
    vertical_margin_emu: int = 0,
    bullet_indent_emu: int = 0,
) -> dict[str, float] | None:
    """预估文字在给定字号下是否会垂直溢出文本框。

    返回值包含估算详情，或 None 表示无法估算（字号未知）。
    """
    if font_size_pt is None or font_size_pt <= 0:
        return None
    box_width_cm = (box_width_emu - horizontal_margin_emu - bullet_indent_emu) / EMU_PER_CM
    box_height_cm = (box_height_emu - vertical_margin_emu) / EMU_PER_CM
    if box_width_cm <= 0 or box_height_cm <= 0:
        return None

    char_width_ratio = CJK_CHAR_WIDTH_RATIO if is_cjk else LATIN_CHAR_WIDTH_RATIO
    char_width_cm = font_size_pt * char_width_ratio
    chars_per_line = max(1, int(box_width_cm / char_width_cm))
    if paragraphs:
        est_lines = sum(
            max(1, (len(line) + chars_per_line - 1) // chars_per_line)
            for paragraph in paragraphs
            for line in (paragraph.split("\n") or [""])
        )
    else:
        est_lines = (chars + chars_per_line - 1) // chars_per_line  # ceil
    line_height_cm = font_size_pt * LINE_HEIGHT_RATIO / 72 * 2.54
    text_height_cm = est_lines * line_height_cm
    fill_ratio = text_height_cm / box_height_cm if box_height_cm > 0 else 999

    return {
        "box_width_cm": round(box_width_cm, 1),
        "box_height_cm": round(box_height_cm, 1),
        "font_size_pt": font_size_pt,
        "char_width_cm": round(char_width_cm, 3),
        "chars_per_line": chars_per_line,
        "horizontal_margin_cm": round(horizontal_margin_emu / EMU_PER_CM, 2),
        "vertical_margin_cm": round(vertical_margin_emu / EMU_PER_CM, 2),
        "bullet_indent_cm": round(bullet_indent_emu / EMU_PER_CM, 2),
        "est_lines": est_lines,
        "line_height_cm": round(line_height_cm, 2),
        "text_height_cm": round(text_height_cm, 1),
        "fill_ratio": round(fill_ratio, 2),           # 展示用舍入
        "fill_ratio_raw": fill_ratio,                   # 原始值，用于阈值判断
    }


def slide_number(name: str) -> int:
    match = re.search(r"slide(\d+)\.xml$", name)
    return int(match.group(1)) if match else 0


def iter_text_containers(root: ET.Element) -> list[tuple[str, ET.Element]]:
    containers: list[tuple[str, ET.Element]] = []
    for shape in root.findall(".//p:sp", NS):
        containers.append(("shape", shape))
    for table_or_chart in root.findall(".//p:graphicFrame", NS):
        if text_of(table_or_chart):
            containers.append(("graphicFrame", table_or_chart))
    return containers


def iter_visible_objects(root: ET.Element) -> list[tuple[str, ET.Element]]:
    """Return text, pictures, connectors, tables/charts, and grouped visible objects."""
    objects: list[tuple[str, ET.Element]] = []
    tags = (("shape", "p:sp"), ("picture", "p:pic"), ("connector", "p:cxnSp"), ("graphicFrame", "p:graphicFrame"), ("group", "p:grpSp"))
    for kind, tag in tags:
        objects.extend((kind, item) for item in root.findall(f".//{tag}", NS))
    return objects


def overlap_area(first: dict[str, int], second: dict[str, int]) -> int:
    left = max(first["x"], second["x"])
    top = max(first["y"], second["y"])
    right = min(first["x"] + first["cx"], second["x"] + second["cx"])
    bottom = min(first["y"] + first["cy"], second["y"] + second["cy"])
    return max(0, right - left) * max(0, bottom - top)


def bounds_contains(
    outer: dict[str, int],
    inner: dict[str, int],
    tolerance: int = ALIGNMENT_TOLERANCE_EMU,
) -> bool:
    """Treat a contained label/image as intentional composition, not object collision."""
    return (
        outer["x"] - tolerance <= inner["x"]
        and outer["y"] - tolerance <= inner["y"]
        and outer["x"] + outer["cx"] + tolerance >= inner["x"] + inner["cx"]
        and outer["y"] + outer["cy"] + tolerance >= inner["y"] + inner["cy"]
    )


def is_background(bounds: dict[str, int], slide_width: int, slide_height: int) -> bool:
    return bounds["cx"] >= slide_width * 0.95 and bounds["cy"] >= slide_height * 0.95


def is_footer_shape(el: ET.Element) -> bool:
    return placeholder_type(el) in {"ftr", "sldNum", "dt"}


def text_box_padding_risk(el: ET.Element) -> bool:
    """Only evaluate explicitly-set margins; inherited defaults remain renderer-owned."""
    body = el.find("./p:txBody/a:bodyPr", NS)
    if body is None:
        return False
    values = [body.attrib.get(key) for key in ("lIns", "rIns", "tIns", "bIns") if key in body.attrib]
    try:
        return any(int(value) < MIN_CARD_PADDING_EMU for value in values)
    except ValueError:
        return False


def text_layout_inputs(el: ET.Element) -> tuple[list[str], int, int, int]:
    paragraphs = [text_of(paragraph) for paragraph in el.findall(".//a:p", NS)]
    body = el.find("./p:txBody/a:bodyPr", NS)
    def value(name: str) -> int:
        try:
            return int(body.attrib.get(name, "0")) if body is not None else 0
        except ValueError:
            return 0
    horizontal_margin = value("lIns") + value("rIns")
    vertical_margin = value("tIns") + value("bIns")
    indents = []
    for ppr in el.findall(".//a:p/a:pPr", NS):
        for name in ("marL", "indent"):
            try:
                indents.append(abs(int(ppr.attrib.get(name, "0"))))
            except ValueError:
                continue
    return paragraphs, horizontal_margin, vertical_margin, max(indents, default=0)


def expanded_connector_bounds(el: ET.Element, bounds: dict[str, int]) -> dict[str, int]:
    line = el.find(".//a:ln", NS)
    try:
        thickness = max(int(line.attrib.get("w", "12700")) if line is not None else 12700, 12700)
    except ValueError:
        thickness = 12700
    return {
        "x": bounds["x"] - thickness,
        "y": bounds["y"] - thickness,
        "cx": max(bounds["cx"], thickness * 2) + thickness * 2,
        "cy": max(bounds["cy"], thickness * 2) + thickness * 2,
    }


def slide_size(zf: zipfile.ZipFile) -> tuple[int, int]:
    root = read_xml(zf, "ppt/presentation.xml")
    if root is not None:
        size = root.find("./p:sldSz", NS)
        if size is not None:
            try:
                return int(size.attrib["cx"]), int(size.attrib["cy"])
            except (KeyError, ValueError):
                pass
    return DEFAULT_SLIDE_WIDTH_EMU, DEFAULT_SLIDE_HEIGHT_EMU


def inspect_pptx(path: Path, max_bytes: int = DEFAULT_MAX_PPTX_BYTES) -> dict:
    findings = []
    detected_fonts: set[str] = set()
    layout_pattern_counts: Counter[str] = Counter()
    try:
        size = path.stat().st_size
        if size > max_bytes:
            return {
                "file": str(path),
                "error": f"PPTX is too large for static scan: {size} bytes > {max_bytes} bytes",
                "note": "Static XML risk scan skipped; use rendered previews and a sampled manual review.",
                "findings": [],
            }
        with zipfile.ZipFile(path) as zf:
            slide_width, slide_height = slide_size(zf)
            slide_names = sorted(
                [n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
                key=slide_number,
            )
            layout_cache: dict[str, dict[str, dict[str, float] | dict[str, str]]] = {}
            for slide_name in slide_names:
                slide_id = slide_number(slide_name)
                root = ET.fromstring(zf.read(slide_name))
                layout_name = relationship_target(zf, slide_name, "/slideLayout")
                layout_cache_key = layout_name or ""
                if layout_cache_key not in layout_cache:
                    layout_cache[layout_cache_key] = inherited_font_context_for_layout(zf, layout_name)
                inherited_context = layout_cache[layout_cache_key]
                bounded_items: list[tuple[int, dict[str, int]]] = []
                visible_objects: list[tuple[str, int, dict[str, int]]] = []
                connector_objects: list[tuple[int, ET.Element, dict[str, int]]] = []
                for object_index, (object_kind, obj) in enumerate(iter_visible_objects(root), start=1):
                    object_bounds = shape_bounds(obj)
                    if object_bounds and not is_background(object_bounds, slide_width, slide_height):
                        visible_objects.append((object_kind, object_index, object_bounds))
                        if object_kind == "connector":
                            connector_objects.append((object_index, obj, object_bounds))
                    if object_kind == "picture" and object_bounds:
                        resolution = picture_resolution(zf, slide_name, obj)
                        if resolution:
                            width_in = object_bounds["cx"] / 914400
                            height_in = object_bounds["cy"] / 914400
                            if width_in < 0.5 or height_in < 0.5:
                                continue  # 跳过装饰性小形状的 PPI 检查
                            effective_ppi = min(resolution[0] / width_in, resolution[1] / height_in)
                            if effective_ppi < 100:
                                findings.append(
                                    {
                                        "slide": slide_id,
                                        "shape": object_index,
                                        "container_type": "picture",
                                        "text_preview": "embedded picture",
                                        "min_font_pt": None,
                                        "font_size_source": "n/a",
                                        "char_count": 0,
                                        "detected_cjk": False,
                                        "heading_shape": False,
                                        "primary_title_shape": False,
                                        "bounds": object_bounds,
                                        "image_resolution_px": {"width": resolution[0], "height": resolution[1]},
                                        "effective_ppi": round(effective_ppi, 1),
                                        "risk": ["low-resolution-image-risk"],
                                    }
                                )
                            source_ratio = resolution[0] / max(resolution[1], 1)
                            display_ratio = object_bounds["cx"] / max(object_bounds["cy"], 1)
                            if abs(source_ratio - display_ratio) / max(source_ratio, 0.01) > 0.08:
                                findings.append(
                                    {
                                        "slide": slide_id,
                                        "shape": object_index,
                                        "container_type": "picture",
                                        "text_preview": "embedded picture",
                                        "min_font_pt": None,
                                        "font_size_source": "n/a",
                                        "char_count": 0,
                                        "detected_cjk": False,
                                        "heading_shape": False,
                                        "primary_title_shape": False,
                                        "bounds": object_bounds,
                                        "image_resolution_px": {"width": resolution[0], "height": resolution[1]},
                                        "risk": ["image-aspect-distortion-risk"],
                                    }
                                )
                    if object_kind == "graphicFrame":
                        chart_name = chart_part(zf, slide_name, obj)
                        chart_root = read_xml(zf, chart_name)
                        if chart_root is not None:
                            chart_risk = []
                            if chart_root.find(".//c:title", NS) is None:
                                chart_risk.append("chart-missing-title-risk")
                            chart_sizes = font_sizes(chart_root)
                            if chart_sizes and min(chart_sizes) < 18:
                                chart_risk.append("chart-label-font-size-below-18pt")
                            if chart_risk:
                                findings.append(
                                    {
                                        "slide": slide_id,
                                        "shape": object_index,
                                        "container_type": "chart",
                                        "text_preview": "embedded chart",
                                        "min_font_pt": min(chart_sizes) if chart_sizes else None,
                                        "font_size_source": "chart-xml",
                                        "char_count": 0,
                                        "detected_cjk": False,
                                        "heading_shape": False,
                                        "primary_title_shape": False,
                                        "bounds": object_bounds,
                                        "risk": chart_risk,
                                    }
                                )
                if visible_objects:
                    signature_counts = Counter(kind for kind, _, _ in visible_objects)
                    signature = ",".join(f"{kind}:{count}" for kind, count in sorted(signature_counts.items()))
                    layout_pattern_counts[signature] += 1
                for idx, (container_type, container) in enumerate(iter_text_containers(root), start=1):
                    txt = text_of(container)
                    if not txt:
                        continue
                    heading = container_type == "shape" and is_heading_shape(container)
                    primary_title = (
                        container_type == "shape" and is_primary_title_shape(container)
                    )
                    sizes = font_sizes(container)
                    font_size_source = "explicit" if sizes else None
                    if not sizes and container_type == "shape":
                        sizes, font_size_source = inherited_font_sizes(container, inherited_context, heading)
                    min_size = min(sizes) if sizes else None
                    bounds = shape_bounds(container)
                    chars = len(txt)
                    is_cjk = has_cjk(txt)
                    paragraphs, horizontal_margin, vertical_margin, bullet_indent = text_layout_inputs(container)
                    risk = []
                    if min_size is None:
                        risk.append("font-size-not-explicit")
                    elif min_size < 20:
                        risk.append("font-size-below-20pt")
                    elif is_cjk and min_size < 22:
                        risk.append("chinese-font-size-below-22pt")
                    if primary_title and min_size is not None and min_size < 24:
                        risk.append("heading-font-size-below-24pt")
                    if container_type == "shape" and text_box_padding_risk(container):
                        risk.append("text-box-padding-below-16pt")
                    if bounds:
                        bounded_items.append((idx, bounds))
                        width_cm = max(bounds["cx"] / EMU_PER_CM, 0.1)
                        if chars / width_cm > TEXT_CHARS_PER_CM_LIMIT:
                            risk.append("high-text-density-overflow-risk")
                        if bounds["cx"] < SMALL_TEXT_BOX_WIDTH_EMU or bounds["cy"] < SMALL_TEXT_BOX_HEIGHT_EMU:
                            risk.append("small-text-box-risk")
                        # 垂直溢出预估：文字总高 vs 盒高
                        overflow = estimate_text_overflow(
                            chars, is_cjk, min_size,
                            bounds["cx"], bounds["cy"],
                            paragraphs=paragraphs,
                            horizontal_margin_emu=horizontal_margin,
                            vertical_margin_emu=vertical_margin,
                            bullet_indent_emu=bullet_indent,
                        )
                        if overflow and overflow["fill_ratio_raw"] > OVERFLOW_BOX_FILL_RATIO:
                            risk.append("text-vertical-overflow-risk")
                        if (
                            bounds["x"] < 0
                            or bounds["y"] < 0
                            or bounds["x"] + bounds["cx"] > slide_width
                            or bounds["y"] + bounds["cy"] > slide_height
                        ):
                            risk.append("shape-outside-slide")
                        elif (
                            bounds["x"] < EDGE_MARGIN_EMU
                            or bounds["y"] < EDGE_MARGIN_EMU
                            or slide_width - (bounds["x"] + bounds["cx"]) < EDGE_MARGIN_EMU
                            or slide_height - (bounds["y"] + bounds["cy"]) < EDGE_MARGIN_EMU
                        ):
                            risk.append("edge-margin-risk")
                        title_zone = slide_height * 0.16
                        footer_start = slide_height * 0.95
                        if primary_title and bounds["y"] + bounds["cy"] > title_zone:
                            risk.append("title-outside-title-zone")
                        if not is_footer_shape(container) and bounds["y"] + bounds["cy"] > footer_start:
                            risk.append("footer-zone-invasion")
                    paragraph_limit = CHINESE_PARAGRAPH_LIMIT if is_cjk else LATIN_PARAGRAPH_LIMIT
                    if chars > paragraph_limit:
                        risk.append("paragraph-heavy-slide-text")
                    colors = fill_colors(container)
                    background_color = solid_fill_color(container)
                    foreground_colors = text_colors(container)
                    if background_color:
                        for foreground_color in foreground_colors:
                            if contrast_ratio(background_color, foreground_color) < 4.5:
                                risk.append("low-foreground-background-contrast")
                                break
                    faces = font_families(container)
                    detected_fonts.update(faces)
                    if len(set(colors)) >= 6:
                        risk.append("many-colors-in-shape")
                    if any(face.casefold() not in PORTABLE_FONT_FAMILIES for face in faces):
                        risk.append("font-compatibility-review-required")
                    if risk:
                        finding = {
                            "slide": slide_id,
                            "shape": idx,
                            "container_type": container_type,
                            "text_preview": txt[:80],
                            "min_font_pt": min_size,
                            "font_size_source": font_size_source or "unknown",
                            "char_count": chars,
                            "detected_cjk": is_cjk,
                            "heading_shape": heading,
                            "primary_title_shape": primary_title,
                            "bounds": bounds,
                            "risk": risk,
                        }
                        if bounds and min_size:
                            overflow_detail = estimate_text_overflow(
                                chars, is_cjk, min_size,
                                bounds["cx"], bounds["cy"],
                                paragraphs=paragraphs,
                                horizontal_margin_emu=horizontal_margin,
                                vertical_margin_emu=vertical_margin,
                                bullet_indent_emu=bullet_indent,
                            )
                            if overflow_detail:
                                finding["overflow_estimate"] = overflow_detail
                        findings.append(finding)
                if bounded_items:
                    total_area = sum(
                        min(item["cx"], slide_width) * min(item["cy"], slide_height)
                        for _, item in bounded_items
                    )
                    slide_area = slide_width * slide_height
                    x_axes = {
                        round(item["x"] / EMU_PER_CM, 1)
                        for _, item in bounded_items
                    }
                    slide_risks = []
                    if total_area / max(slide_area, 1) > 0.92:
                        slide_risks.append("low-whitespace-risk")
                    if len(bounded_items) >= 7 and len(x_axes) >= 6:
                        slide_risks.append("alignment-axis-complexity")
                    if slide_risks:
                        findings.append(
                            {
                                "slide": slide_id,
                                "shape": 0,
                                "container_type": "slide",
                                "text_preview": "slide-level geometry",
                                "min_font_pt": None,
                                "font_size_source": "n/a",
                                "char_count": 0,
                                "detected_cjk": False,
                                "heading_shape": False,
                                "primary_title_shape": False,
                                "bounds": {
                                    "x": 0,
                                    "y": 0,
                                    "cx": slide_width,
                                    "cy": slide_height,
                                },
                                "risk": slide_risks,
                            }
                        )
                overlap_examples = []
                gutter_examples = []
                for first_index, (first_kind, first_id, first_bounds) in enumerate(visible_objects):
                    if first_kind == "connector":
                        continue
                    for second_kind, second_id, second_bounds in visible_objects[first_index + 1:]:
                        if second_kind == "connector":
                            continue
                        if bounds_contains(first_bounds, second_bounds) or bounds_contains(
                            second_bounds, first_bounds
                        ):
                            continue
                        area = overlap_area(first_bounds, second_bounds)
                        min_area = min(first_bounds["cx"] * first_bounds["cy"], second_bounds["cx"] * second_bounds["cy"])
                        if area >= MIN_UNINTENDED_OVERLAP_EMU ** 2 and area / max(min_area, 1) >= 0.15:
                            overlap_examples.append({"first": f"{first_kind}:{first_id}", "second": f"{second_kind}:{second_id}", "area_emu2": area})
                        vertical_overlap = min(first_bounds["y"] + first_bounds["cy"], second_bounds["y"] + second_bounds["cy"]) - max(first_bounds["y"], second_bounds["y"])
                        horizontal_overlap = min(first_bounds["x"] + first_bounds["cx"], second_bounds["x"] + second_bounds["cx"]) - max(first_bounds["x"], second_bounds["x"])
                        horizontal_gap = max(second_bounds["x"] - (first_bounds["x"] + first_bounds["cx"]), first_bounds["x"] - (second_bounds["x"] + second_bounds["cx"]), 0)
                        vertical_gap = max(second_bounds["y"] - (first_bounds["y"] + first_bounds["cy"]), first_bounds["y"] - (second_bounds["y"] + second_bounds["cy"]), 0)
                        if (vertical_overlap > 0 and 0 < horizontal_gap < MIN_GUTTER_EMU) or (horizontal_overlap > 0 and 0 < vertical_gap < MIN_GUTTER_EMU):
                            gutter_examples.append({"first": f"{first_kind}:{first_id}", "second": f"{second_kind}:{second_id}", "gap_emu": min(horizontal_gap or MIN_GUTTER_EMU, vertical_gap or MIN_GUTTER_EMU)})
                if overlap_examples:
                    findings.append(
                        {
                            "slide": slide_id,
                            "shape": 0,
                            "container_type": "slide",
                            "text_preview": "slide-level object overlap",
                            "min_font_pt": None,
                            "font_size_source": "n/a",
                            "char_count": 0,
                            "detected_cjk": False,
                            "heading_shape": False,
                            "primary_title_shape": False,
                            "risk": ["unexpected-object-overlap-risk"],
                            "overlap_examples": overlap_examples[:10],
                        }
                    )
                if gutter_examples:
                    findings.append(
                        {
                            "slide": slide_id,
                            "shape": 0,
                            "container_type": "slide",
                            "text_preview": "slide-level gutter spacing",
                            "min_font_pt": None,
                            "font_size_source": "n/a",
                            "char_count": 0,
                            "detected_cjk": False,
                            "heading_shape": False,
                            "primary_title_shape": False,
                            "risk": ["insufficient-gutter-risk"],
                            "gutter_examples": gutter_examples[:10],
                        }
                    )
                alignment_examples = []
                containment_examples = []
                for first_index, (first_kind, first_id, first_bounds) in enumerate(visible_objects):
                    if first_kind == "connector":
                        continue
                    for second_kind, second_id, second_bounds in visible_objects[first_index + 1:]:
                        if second_kind == "connector":
                            continue
                        horizontal_overlap = min(first_bounds["x"] + first_bounds["cx"], second_bounds["x"] + second_bounds["cx"]) - max(first_bounds["x"], second_bounds["x"])
                        vertical_gap = max(second_bounds["y"] - (first_bounds["y"] + first_bounds["cy"]), first_bounds["y"] - (second_bounds["y"] + second_bounds["cy"]), 0)
                        x_delta = abs(first_bounds["x"] - second_bounds["x"])
                        if horizontal_overlap > min(first_bounds["cx"], second_bounds["cx"]) * 0.7 and vertical_gap >= MIN_GUTTER_EMU and ALIGNMENT_TOLERANCE_EMU < x_delta <= MIN_GUTTER_EMU:
                            alignment_examples.append({"first": f"{first_kind}:{first_id}", "second": f"{second_kind}:{second_id}", "left_edge_delta_emu": x_delta})
                        first_contains_second = (
                            first_bounds["x"] <= second_bounds["x"]
                            and first_bounds["y"] <= second_bounds["y"]
                            and first_bounds["x"] + first_bounds["cx"] >= second_bounds["x"] + second_bounds["cx"]
                            and first_bounds["y"] + first_bounds["cy"] >= second_bounds["y"] + second_bounds["cy"]
                        )
                        second_contains_first = (
                            second_bounds["x"] <= first_bounds["x"]
                            and second_bounds["y"] <= first_bounds["y"]
                            and second_bounds["x"] + second_bounds["cx"] >= first_bounds["x"] + first_bounds["cx"]
                            and second_bounds["y"] + second_bounds["cy"] >= first_bounds["y"] + first_bounds["cy"]
                        )
                        if (first_contains_second or second_contains_first) and first_kind == second_kind == "picture":
                            containment_examples.append({"first": f"{first_kind}:{first_id}", "second": f"{second_kind}:{second_id}"})
                if alignment_examples:
                    findings.append(
                        {
                            "slide": slide_id, "shape": 0, "container_type": "slide", "text_preview": "slide-level alignment",
                            "min_font_pt": None, "font_size_source": "n/a", "char_count": 0, "detected_cjk": False,
                            "heading_shape": False, "primary_title_shape": False,
                            "risk": ["alignment-tolerance-risk"], "alignment_examples": alignment_examples[:10],
                        }
                    )
                if containment_examples:
                    findings.append(
                        {
                            "slide": slide_id, "shape": 0, "container_type": "slide", "text_preview": "picture containment",
                            "min_font_pt": None, "font_size_source": "n/a", "char_count": 0, "detected_cjk": False,
                            "heading_shape": False, "primary_title_shape": False,
                            "risk": ["picture-contained-by-picture-review"], "containment_examples": containment_examples[:10],
                        }
                    )
                connector_crossings = []
                for connector_id, connector, connector_bounds in connector_objects:
                    corridor = expanded_connector_bounds(connector, connector_bounds)
                    for object_kind, object_id, object_bounds in visible_objects:
                        if object_kind == "connector":
                            continue
                        area = overlap_area(corridor, object_bounds)
                        # Ignore an endpoint touching a node; a meaningful intersection means a route crosses its interior.
                        if area > MIN_UNINTENDED_OVERLAP_EMU ** 2:
                            connector_crossings.append({"connector": connector_id, "crosses": f"{object_kind}:{object_id}"})
                if connector_crossings:
                    findings.append(
                        {
                            "slide": slide_id,
                            "shape": 0,
                            "container_type": "slide",
                            "text_preview": "connector routing",
                            "min_font_pt": None,
                            "font_size_source": "n/a",
                            "char_count": 0,
                            "detected_cjk": False,
                            "heading_shape": False,
                            "primary_title_shape": False,
                            "risk": ["connector-crosses-object-risk"],
                            "connector_crossings": connector_crossings[:10],
                        }
                    )
    except (FileNotFoundError, PermissionError, OSError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        return {
            "file": str(path),
            "error": str(exc),
            "note": "Static XML risk scan failed; status is blocked until the file can be read.",
            "findings": [],
        }
    return {
        "file": str(path),
        "note": (
            "Static XML risk scan only; status remains incomplete until rendered previews are inspected. "
            "Common layout/master inherited font sizes are resolved, but PowerPoint rendering may still differ."
        ),
        "font_families": sorted(detected_fonts),
        "deck_statistics": {
            "layout_pattern_counts": dict(sorted(layout_pattern_counts.items())),
            "distinct_layout_patterns": len(layout_pattern_counts),
        },
        "findings": findings,
    }


def summarize_static_risks(static_result: dict[str, object]) -> dict[str, object]:
    """Classify findings consistently for generation and delivery gates."""
    findings = static_result.get("findings", []) if isinstance(static_result, dict) else []
    risk_counter: Counter[str] = Counter()
    acceptable_minor_counter: Counter[str] = Counter()
    blocker_like: list[dict[str, object]] = []
    minor_markers = (
        "footer",
        "page",
        "slide",
        "source",
        "caption",
        "kicker",
        "eyebrow",
        "页码",
        "来源",
        "注释",
    )
    blocker_risks = {
        "high-text-density-overflow-risk",
        "text-vertical-overflow-risk",
        "paragraph-heavy-slide-text",
        "heading-font-size-below-24pt",
        "shape-outside-slide",
        "low-whitespace-risk",
        "unexpected-object-overlap-risk",
        "low-resolution-image-risk",
        "image-aspect-distortion-risk",
        "title-outside-title-zone",
        "footer-zone-invasion",
        "insufficient-gutter-risk",
        "low-foreground-background-contrast",
        "connector-crosses-object-risk",
        "chart-missing-title-risk",
        "chart-label-font-size-below-18pt",
        "text-box-padding-below-16pt",
        "alignment-tolerance-risk",
    }
    for item in findings if isinstance(findings, list) else []:
        if not isinstance(item, dict):
            continue
        risks = item.get("risk", []) or []
        text_preview = str(item.get("text_preview", ""))
        lower_preview = text_preview.lower()
        min_font = item.get("min_font_pt")
        char_count = item.get("char_count") or 0
        looks_minor = (
            isinstance(char_count, (int, float))
            and char_count <= 24
            and isinstance(min_font, (int, float))
            and min_font >= 10
            and any(marker in lower_preview or marker in text_preview for marker in minor_markers)
        )
        for risk in risks if isinstance(risks, list) else []:
            risk_counter[str(risk)] += 1
            if looks_minor and risk in {
                "font-size-below-20pt",
                "chinese-font-size-below-22pt",
                "small-text-box-risk",
            }:
                acceptable_minor_counter[str(risk)] += 1
        if any(risk in blocker_risks for risk in risks) and not looks_minor:
            blocker_like.append(
                {
                    "slide": item.get("slide"),
                    "shape": item.get("shape"),
                    "text_preview": text_preview[:80],
                    "risk": risks,
                    "min_font_pt": min_font,
                }
            )
    return {
        "risk_breakdown": dict(sorted(risk_counter.items())),
        "acceptable_minor_risk_breakdown": dict(sorted(acceptable_minor_counter.items())),
        "blocker_like_count": len(blocker_like),
        "blocker_like_examples": blocker_like[:10],
    }
