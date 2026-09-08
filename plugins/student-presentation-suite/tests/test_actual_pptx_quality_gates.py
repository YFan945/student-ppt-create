from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN_ROOT / "scripts"
EMU = 914400


def _write_pptx(path: Path, *, x: float = 0.8, y: float = 0.8, w: float = 5.0, h: float = 1.0, text: str = "42% Result") -> None:
    presentation = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">
  <p:sldSz cx="{10 * EMU}" cy="{int(5.625 * EMU)}"/>
</p:presentation>'''
    slide = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp>
    <p:nvSpPr><p:cNvPr id="2" name="Title 1"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>
    <p:spPr><a:xfrm><a:off x="{int(x * EMU)}" y="{int(y * EMU)}"/><a:ext cx="{int(w * EMU)}" cy="{int(h * EMU)}"/></a:xfrm></p:spPr>
    <p:txBody><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr sz="2400"/><a:t>{text}</a:t></a:r></a:p></p:txBody>
  </p:sp></p:spTree></p:cSld>
</p:sld>'''
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/slides/slide1.xml", slide)


def _run_json(script: str, *args: str) -> tuple[int, dict]:
    completed = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *args, "--json"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.stdout, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def test_static_analyzer_checks_actual_bbox(tmp_path: Path) -> None:
    pptx = tmp_path / "good.pptx"
    _write_pptx(pptx)
    code, report = _run_json("pptx_static_analyzer.py", str(pptx), "--strict")
    assert code == 0
    assert report["ok"] is True
    assert report["slide_count"] == 1
    assert report["slides"][0]["element_count"] == 1


def test_static_analyzer_blocks_out_of_canvas(tmp_path: Path) -> None:
    pptx = tmp_path / "bad.pptx"
    _write_pptx(pptx, x=9.7, w=1.0)
    code, report = _run_json("pptx_static_analyzer.py", str(pptx), "--strict")
    assert code == 2
    assert report["ok"] is False
    assert any(item["code"] == "out_of_canvas" for item in report["findings"])


def test_plan_check_binds_title_and_key_number_to_actual_slide(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    spec = tmp_path / "spec.yaml"
    _write_pptx(pptx, text="42% Result")
    spec.write_text(
        yaml.safe_dump(
            {
                "slides": [
                    {
                        "id": 1,
                        "title": "42% Result",
                        "layout": "hero",
                        "content": "42% Result",
                        "timing_sec": 30,
                        "owner": "Individual",
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    code, report = _run_json("pptx_plan_check.py", str(spec), str(pptx), "--strict")
    assert code == 0
    assert report["ok"] is True
    assert report["actual_slide_count"] == 1


def test_plan_check_detects_title_drift(tmp_path: Path) -> None:
    pptx = tmp_path / "deck.pptx"
    spec = tmp_path / "spec.yaml"
    _write_pptx(pptx, text="Actual content")
    spec.write_text(
        yaml.safe_dump(
            {
                "slides": [
                    {
                        "id": 1,
                        "title": "Planned conclusion 42%",
                        "layout": "hero",
                        "content": "Planned conclusion 42%",
                        "timing_sec": 30,
                        "owner": "Individual",
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    code, report = _run_json("pptx_plan_check.py", str(spec), str(pptx), "--strict")
    assert code == 2
    assert report["ok"] is False
    codes = {item["code"] for item in report["findings"]}
    assert "title_drift" in codes
    assert "planned_number_missing" in codes
