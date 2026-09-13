"""Rewrite CJK (East Asian) typefaces inside a generated PPTX.

pptxgenjs only emits ``<a:latin typeface="..."/>``; CJK glyphs therefore fall
back to the viewer's default East Asian font and the deck loses its intended
typographic personality. This module post-processes slide XML so every run
whose latin typeface matches a known title/body font also carries a matching
``<a:ea typeface="..."/>`` element.
"""

from __future__ import annotations

import os
import re
import shutil
import time
import zipfile
from pathlib import Path

from lxml import etree

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
NS = {"a": A_NS}
SLIDE_PART = re.compile(r"^ppt/(slides|slideMasters|slideLayouts|notesSlides)/[^/]+\.xml$")

# 解压后体积与压缩比上限：与 package.py 的防线保持一致，避免 zip bomb。
_MAX_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_RATIO = 200


def _safe_parser() -> etree.XMLParser:
    """用户提供的 PPTX 不可信：禁用实体解析、外部 DTD 与网络访问。

    全仓其余 XML 入口统一使用 defusedxml，这里是唯一直接用 lxml 的地方，
    必须显式关掉实体展开，否则恶意文档可触发实体膨胀（billion laughs）。
    """
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        huge_tree=False,
    )


def parse_font_map(pairs: list[str]) -> dict[str, str]:
    """Parse ``Latin=CJK`` CLI pairs into a mapping dict."""
    mapping: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--map expects Latin=CJK, got {pair!r}")
        latin, cjk = pair.split("=", 1)
        latin, cjk = latin.strip(), cjk.strip()
        if not latin or not cjk:
            raise ValueError(f"--map expects Latin=CJK, got {pair!r}")
        mapping[latin] = cjk
    return mapping


def _add_ea_typefaces(xml_bytes: bytes, mapping: dict[str, str]) -> tuple[bytes, int]:
    root = etree.fromstring(xml_bytes, parser=_safe_parser())
    changed = 0
    for latin in root.iter(f"{{{A_NS}}}latin"):
        face = latin.get("typeface") or ""
        cjk = mapping.get(face)
        if not cjk:
            continue
        parent = latin.getparent()
        if parent is None:
            continue
        existing = parent.find(f"{{{A_NS}}}ea")
        if existing is not None:
            if existing.get("typeface") != cjk:
                existing.set("typeface", cjk)
                changed += 1
            continue
        ea = etree.SubElement(parent, f"{{{A_NS}}}ea")
        ea.set("typeface", cjk)
        latin.addnext(ea)
        changed += 1
    if not changed:
        return xml_bytes, 0
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True), changed


def _write_package(entries: list[tuple[zipfile.ZipInfo, bytes]], target: Path) -> None:
    """先写临时文件再原子替换，绝不直接写回输入文件。

    旧实现以 ``"w"`` 直接打开输入文件本身：写入中途异常、断电或磁盘满会
    **截断并永久损毁用户原件**，而 docstring 声称的"原子替换"并不存在
    （原注释说这是为了规避 Windows 杀毒软件对临时文件的短时锁定）。

    现在的策略：
    1. 写 ``.cjk-tmp`` 临时文件 → ``os.replace`` 原子替换；
    2. 替换被占用时重试若干次（杀毒锁通常只持续几秒）；
    3. 仍失败才退化为"先备份原件再原地写"，保证最坏情况下用户仍有 ``.bak`` 可恢复。
    """
    tmp = target.with_name(f".{target.name}.cjk-tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for item, data in entries:
            dst.writestr(item, data)
    for attempt in range(6):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == 5:
                break
            time.sleep(0.3)
    backup = target.with_name(f"{target.name}.bak")
    shutil.copy2(target, backup)
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as dst:
            for item, data in entries:
                dst.writestr(item, data)
    finally:
        tmp.unlink(missing_ok=True)


def apply_cjk_fonts(pptx: Path, mapping: dict[str, str], output: Path | None = None) -> int:
    """Add ``<a:ea>`` typefaces for every mapped latin font. Returns element count.

    Rewrites the package atomically: content is staged in a sibling temp file
    and moved into place, so a failure never truncates the input deck.
    When ``output`` is None and nothing changes, the input file is left untouched.
    """
    if not mapping:
        raise ValueError("cjk font mapping is empty")
    target = Path(output) if output is not None else Path(pptx)
    total = 0
    entries: list[tuple[zipfile.ZipInfo, bytes]] = []
    uncompressed = 0
    with zipfile.ZipFile(pptx, "r") as src:
        for item in src.infolist():
            data = src.read(item.filename)
            uncompressed += len(data)
            if uncompressed > _MAX_TOTAL_BYTES:
                raise ValueError("PPTX content exceeds the safe uncompressed size limit")
            if item.compress_size > 0 and len(data) / item.compress_size > _MAX_RATIO:
                raise ValueError(f"Suspicious compression ratio in {item.filename!r}")
            if SLIDE_PART.match(item.filename) and b"a:latin" in data:
                data, changed = _add_ea_typefaces(data, mapping)
                total += changed
            entries.append((item, data))
    # 没有任何改动就不要重写用户原件（旧实现无条件重写整个包）。
    if not total and output is None:
        return 0
    _write_package(entries, target)
    return total
