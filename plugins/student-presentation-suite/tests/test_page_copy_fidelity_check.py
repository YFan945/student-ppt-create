"""Behavioural contracts for the pre-build page copy fidelity gate.

The gate exists because `pptx_actual_content_check.py` only runs after build and
render, so a paraphrased page module used to be discovered at QA -- after the
expensive stages were paid for. These tests pin both directions: a faithful page
must pass, and a paraphrased page must be refused before `build` runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "sp-deck" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import page_copy_fidelity_check as fidelity  # noqa: E402

SPEC = {
    "schema_version": "1.1",
    "slides": [
        {
            "id": 1,
            "title": "光伏与风电的度电成本对比",
            "claim": "比较光伏与风电谁更便宜，前提是先说清楚用哪一把尺子。",
            "slide_copy": [
                "全球口径：风电 0.034 美元/度",
                "美国口径：两者区间重叠",
            ],
        }
    ],
}


def module(body: str) -> str:
    return "'use strict';\nmodule.exports = function (ctx) {\n" + body + "\n};\n"


def write_page(tmp_path: Path, name: str, body: str) -> Path:
    pages = tmp_path / "pages"
    pages.mkdir(exist_ok=True)
    page = pages / name
    page.write_text(module(body), encoding="utf-8")
    return page


def text_call(value: str) -> str:
    return f"  ctx.slide.addText('{value}', {{}});"


def test_verbatim_page_passes(tmp_path: Path) -> None:
    slide = SPEC["slides"][0]
    body = "\n".join([
        text_call(slide["title"]),
        text_call(slide["claim"]),
        text_call(slide["slide_copy"][0]),
        text_call(slide["slide_copy"][1]),
    ])
    page = write_page(tmp_path, "p01-cost.js", body)
    report = fidelity.check(SPEC, [page])
    assert report["ok"] is True
    assert report["blocker_count"] == 0


def test_paraphrased_claim_is_blocked(tmp_path: Path) -> None:
    body = "\n".join([
        text_call("光伏与风电的度电成本对比"),
        text_call("谁更便宜取决于统计口径，不能一概而论。"),
        text_call("全球口径：风电 0.034 美元/度"),
        text_call("美国口径：两者区间重叠"),
    ])
    page = write_page(tmp_path, "p01-cost.js", body)
    report = fidelity.check(SPEC, [page])
    assert report["ok"] is False
    assert [issue["code"] for issue in report["issues"]] == ["missing_key_claim"]


def test_paraphrased_copy_is_blocked_with_the_original_text(tmp_path: Path) -> None:
    slide = SPEC["slides"][0]
    body = "\n".join([
        text_call(slide["title"]),
        text_call(slide["claim"]),
        text_call("全球口径下风电更便宜"),
        text_call(slide["slide_copy"][1]),
    ])
    page = write_page(tmp_path, "p01-cost.js", body)
    report = fidelity.check(SPEC, [page])
    missing = [issue for issue in report["issues"] if issue["code"] == "planned_copy_missing"]
    assert len(missing) == 1
    # The model must be told the exact string to restore, not just that one is missing.
    assert missing[0]["text"] == "全球口径：风电 0.034 美元/度"


def test_concatenated_literal_still_passes(tmp_path: Path) -> None:
    """`'a' + 'b'` does carry the planned copy; only a real paraphrase is a blocker."""
    slide = SPEC["slides"][0]
    body = "\n".join([
        text_call(slide["title"]),
        text_call(slide["claim"]),
        "  ctx.slide.addText('全球口径：风电 0.034 ' + '美元/度', {});",
        text_call(slide["slide_copy"][1]),
    ])
    page = write_page(tmp_path, "p01-cost.js", body)
    assert fidelity.check(SPEC, [page])["ok"] is True


def test_pages_map_by_ordinal_not_by_slug(tmp_path: Path) -> None:
    """`p03-lcoe.js` is slide 3 even though the slug is not the slide id."""
    spec = {
        "slides": [
            {"id": 1, "title": "第一页标题内容", "claim": "第一页的主张内容", "slide_copy": []},
            {"id": 2, "title": "第二页标题内容", "claim": "第二页的主张内容", "slide_copy": []},
            {"id": 3, "title": "第三页标题内容", "claim": "第三页的主张内容", "slide_copy": []},
        ]
    }
    pages = [
        write_page(tmp_path, "p01-cover.js", text_call("第三页标题内容") + "\n" + text_call("第三页的主张内容")),
        write_page(tmp_path, "p02-x.js", text_call("第二页标题内容") + "\n" + text_call("第二页的主张内容")),
        write_page(tmp_path, "p03-lcoe.js", text_call("第一页标题内容") + "\n" + text_call("第一页的主张内容")),
    ]
    pages.sort()
    report = fidelity.check(spec, pages)
    # Matching is by ordinal: p02 carries slide 2's copy and passes, while p01 and
    # p03 hold another slide's copy and are reported against their own ordinal.
    assert sorted(issue["slide"] for issue in report["issues"]) == [1, 1, 3, 3]
    assert report["slides"][1]["ok"] is True
    assert report["slides"][0]["ok"] is False
    assert report["slides"][2]["ok"] is False


def test_missing_page_module_is_blocked(tmp_path: Path) -> None:
    spec = {
        "slides": [
            {"id": 1, "title": "第一页标题内容", "claim": "第一页的主张内容", "slide_copy": []},
            {"id": 2, "title": "第二页标题内容", "claim": "第二页的主张内容", "slide_copy": []},
        ]
    }
    page = write_page(tmp_path, "p01-cover.js", text_call("第一页标题内容") + "\n" + text_call("第一页的主张内容"))
    report = fidelity.check(spec, [page])
    assert report["issues"][0]["code"] == "page_module_missing"
    assert report["issues"][0]["slide"] == 2


def test_cli_reports_and_exits_two(tmp_path: Path) -> None:
    spec_path = tmp_path / "slide-spec.json"
    spec_path.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
    write_page(tmp_path, "p01-cost.js", text_call("光伏与风电的度电成本对比"))
    output = tmp_path / "page-copy-fidelity.json"

    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "page_copy_fidelity_check.py"),
         "--slide-spec", str(spec_path), "--pages-dir", str(tmp_path / "pages"),
         "--output", str(output)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 2
    assert "page_copy_fidelity: blocked" in proc.stdout
    assert output.is_file()


def test_cli_passes_without_page_modules(tmp_path: Path) -> None:
    """Nothing scaffolded yet: `assert_page_split` owns that contract, not this gate."""
    spec_path = tmp_path / "slide-spec.json"
    spec_path.write_text(json.dumps(SPEC, ensure_ascii=False), encoding="utf-8")
    empty = tmp_path / "pages"
    empty.mkdir()
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS / "page_copy_fidelity_check.py"),
         "--slide-spec", str(spec_path), "--pages-dir", str(empty),
         "--output", str(tmp_path / "report.json")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert proc.returncode == 0


@pytest.mark.parametrize("fragment", ["", "短", "0.03"])
def test_short_fragments_are_ignored(tmp_path: Path, fragment: str) -> None:
    spec = {"slides": [{"id": 1, "title": "一个足够长的标题", "claim": "", "slide_copy": [fragment]}]}
    page = write_page(tmp_path, "p01-a.js", text_call("一个足够长的标题"))
    assert fidelity.check(spec, [page])["ok"] is True
