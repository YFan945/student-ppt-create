"""normalize-generated folds CJK <a:ea> injection into the build's single pass.

pptxgenjs only writes <a:latin>, so a generated deck used to reach PowerPoint
with no East Asian typeface at all — the mapping existed in the tokens and the
examples ran cjk-fonts by hand, but the production build never injected it.
These tests lock the folded pass: same normalize step, no extra process.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"

SLIDE_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
    'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
    "<p:cSld><p:spTree><p:sp><p:txBody>"
    '<a:p><a:r><a:rPr lang="zh-CN" sz="2200" dirty="0">'
    '<a:latin typeface="Cambria"/></a:rPr><a:t>标题</a:t></a:r></a:p>'
    '<a:p><a:r><a:rPr lang="zh-CN" sz="1800" dirty="0">'
    '<a:latin typeface="Calibri"/><a:ea typeface="FangSong"/></a:rPr>'
    "<a:t>正文</a:t></a:r></a:p>"
    "</p:txBody></p:sp></p:spTree></p:cSld></p:sld>"
)

CONTENT_TYPES = (
    '<?xml version="1.0"?><Types '
    'xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    "</Types>"
)


def write_fixture(root: Path, name: str) -> Path:
    pptx = root / name
    with zipfile.ZipFile(pptx, "w") as zf:
        zf.writestr("[Content_Types].xml", CONTENT_TYPES)
        zf.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="ppt/presentation.xml"/></Relationships>',
        )
        zf.writestr(
            "ppt/presentation.xml",
            '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
            "</p:presentation>",
        )
        zf.writestr("ppt/slides/slide1.xml", SLIDE_XML)
    return pptx


def latin_ea_pairs(path: Path) -> list[tuple[str, str | None, int | None]]:
    """Per rPr: (latin typeface, ea typeface or None, ea offset after latin).

    The offset is the element distance between latin and ea (1 = immediately
    after, which is the schema-correct slot); None when there is no ea.
    """
    with zipfile.ZipFile(path) as zf:
        root = ET.fromstring(zf.read("ppt/slides/slide1.xml"))
    pairs: list[tuple[str, str | None, int | None]] = []
    for rpr in root.iter(f"{{{A_NS}}}rPr"):
        latin = rpr.find(f"{{{A_NS}}}latin")
        if latin is None:
            continue
        ea = rpr.find(f"{{{A_NS}}}ea")
        if ea is None:
            pairs.append((latin.get("typeface") or "", None, None))
        else:
            offset = list(rpr).index(ea) - list(rpr).index(latin)
            pairs.append((latin.get("typeface") or "", ea.get("typeface") or "", offset))
    return pairs


class NormalizeCjkTests(unittest.TestCase):
    def test_cjk_map_injects_ea_after_latin(self) -> None:
        from shared.pptx_runtime.normalize import normalize_generated_package

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_fixture(root, "raw.pptx")
            output = root / "final.pptx"
            changed = normalize_generated_package(source, output, cjk_map={"Cambria": "SimHei"})
            self.assertTrue(any("a:ea" in item for item in changed), changed)
            pairs = {face: (ea, offset) for face, ea, offset in latin_ea_pairs(output)}
            # 映射的 latin 拿到紧随其后的 ea（schema 序：latin, ea, cs）……
            self.assertEqual(("SimHei", 1), pairs["Cambria"])
            # ……已有的 ea 即使未被映射也保持原样。
            self.assertEqual(("FangSong", 1), pairs["Calibri"])

    def test_no_map_leaves_runs_untouched(self) -> None:
        from shared.pptx_runtime.normalize import normalize_generated_package

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_fixture(root, "raw.pptx")
            output = root / "final.pptx"
            normalize_generated_package(source, output)
            pairs = {face: ea for face, ea, _ in latin_ea_pairs(output)}
            self.assertIsNone(pairs["Cambria"])
            self.assertEqual("FangSong", pairs["Calibri"])

    def test_cli_accepts_repeatable_cjk_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_fixture(root, "raw.pptx")
            output = root / "final.pptx"
            tool = ROOT / "scripts" / "pptx_tool.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(tool),
                    "normalize-generated",
                    str(source),
                    "--output",
                    str(output),
                    "--cjk-map",
                    "Cambria=SimHei",
                    "--cjk-map",
                    "Calibri=DengXian",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(0, proc.returncode, proc.stderr or proc.stdout)
            pairs = {face: ea for face, ea, _ in latin_ea_pairs(output)}
            self.assertEqual("SimHei", pairs["Cambria"])
            self.assertEqual("DengXian", pairs["Calibri"])

    def test_cli_rejects_malformed_map(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = write_fixture(root, "raw.pptx")
            output = root / "final.pptx"
            tool = ROOT / "scripts" / "pptx_tool.py"
            proc = subprocess.run(
                [
                    sys.executable,
                    str(tool),
                    "normalize-generated",
                    str(source),
                    "--output",
                    str(output),
                    "--cjk-map",
                    "CambriaSimHei",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertNotEqual(0, proc.returncode)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
