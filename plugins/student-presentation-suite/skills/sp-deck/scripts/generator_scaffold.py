#!/usr/bin/env python3
"""Write the CD-2 generator layout: thin deck.js + one pages/pNN-*.js per slide.

v0.8 still requires composition JSON; this module only creates the *generator*
files so `ppt_pipeline.py build` can refuse a monolithic deck.js. Existing
authored page files (no scaffold marker) are left untouched on replan.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _enforce_pipeline_hook_health() -> None:
    """Run before ppt_pipeline plan does any production work.

    ppt_pipeline imports this module before command dispatch. Keeping the small
    bootstrap here lets the verifier fail before intake/research/preflight while
    avoiding a second copy of hook-health logic in the large pipeline module.
    """
    plugin_root = Path(
        os.environ.get("CLAUDE_PLUGIN_ROOT")
        or Path(__file__).resolve().parent.parents[2]
    ).resolve()
    scripts = plugin_root / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from hook_health import enforce_pipeline_plan_bootstrap

    enforce_pipeline_plan_bootstrap()


_enforce_pipeline_hook_health()

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import pptx_actual_content_check as actual_check  # noqa: E402

SCAFFOLD_MARKER = "student-presentation-suite-scaffold"
PAGE_NAME_RE = re.compile(r"^p(\d{2})-.+\.js$")

DECK_TEMPLATE = """\
'use strict';
/* {marker} — assembly only; page coordinates live in ./pages/pNN-*.js */

const path = require('node:path');
const HELPERS_DIR =
  process.env.PPTX_HELPERS_DIR || path.join(process.env.CLAUDE_PLUGIN_ROOT || '', 'scripts');
const H = require(path.join(HELPERS_DIR, 'pptx-helpers.js'));
const L = require(path.join(HELPERS_DIR, 'pptx-layouts.js'));
const {{ SlideElementRegistry }} = require(path.join(HELPERS_DIR, 'pptx-element-registry.js'));
const pptxgen = require('pptxgenjs');

// 解析好的设计 token 由 scaffold 内联（同源：shared/design_tokens.resolve_design_tokens）。
// 页模块只用这些角色色与字体，不要手写十六进制色值。
const TOKENS = {tokens_json};

const PAGES = [
{requires}
];

function main() {{
  const out = process.argv[2];
  if (!out) throw new Error('usage: deck.js <output.pptx>');
  const pptx = new pptxgen();
  H.applyTokens(pptx, TOKENS, 'chinese');
  const registry = new SlideElementRegistry({{
    slideW: H.SLIDE_W_IN,
    slideH: H.SLIDE_H_IN,
  }});
  // 每页 renderArchetype 把选中的 archetype 记进来，build 后写 sidecar 留档。
  const layoutReport = [];
  PAGES.forEach((mod, index) => {{
    const n = index + 1;
    const slide = pptx.addSlide();
    const ctx = {{ pptx, slide, n, H, registry, tokens: TOKENS, slideNumber: n, layoutReport }};
    if (typeof mod === 'function') {{
      // 函数式页面（自定义坐标的 D9 转义口）：glue 由页面自己执行。
      mod(ctx);
    }} else {{
      // 声明式页面：只填槽位，glue 由 renderDeclaredPage 统一执行。
      L.renderDeclaredPage(ctx, mod);
    }}
  }});
  registry.assertSafe();
  // 完整几何分析（含 warning）写 sidecar，供确定性 QA 带进 repair packet。
  registry.writeReport(out);
  require('node:fs').writeFileSync(
    `${{out}}.layout-report.json`,
    `${{JSON.stringify(layoutReport, null, 2)}}\\n`,
    'utf8',
  );
  // 把 Latin→CJK 字体映射写给构建器：normalize-generated 在同一步注入 <a:ea>，
  // 否则东亚字形回落到查看器默认字体（pptxgenjs 只写 <a:latin>）。
  H.writeCjkMap(out, TOKENS);
  return pptx.writeFile({{ fileName: out }});
}}

main();
"""

PAGE_STUB = """\
'use strict';
/* {marker} */
/** Slide {n} — {title} */
{on_screen_block}
const COPY = {{
  title: {title_js},
  claim: {claim_js},
  keyLine: {key_line_js},
  slideCopy: {copy_js},{sources_line}
}};
/* Keep COPY.* string literals — page_copy_fidelity_check reads this file. */

/* 声明式页面：只填槽位与参数，glue（背景/深浅盘/版式渲染/D11 收尾带/notes）由
   deck.js 的 L.renderDeclaredPage 统一执行。需要自定义坐标时才改回函数式页面
   （module.exports = function (ctx) {{…}}）并在页内注释声明 custom 理由；几何门
   照常全检。slots.key_line 非空时 D11 收尾带自动渲染，不要手画第二条；来源行
   （11pt）画在更下方的 footer 区。 */
module.exports = {{
  dark: {dark_js},
  kind: {kind_js},
  context: {context_js},
  /* 需要钉版式时填 id（如 "cover-split"）；留空由引擎按 context 自选。 */
  layout: undefined,
  slots: {{
    title: COPY.title,
    claim: COPY.claim || undefined,
    key_line: COPY.keyLine || undefined,
    body: Array.isArray(COPY.slideCopy)
      ? COPY.slideCopy
      : COPY.slideCopy
        ? [COPY.slideCopy]
        : undefined,
    visual: {visual_js},
  }},
  params: {{}},
  /* 每页一次、纯文本讲稿（PPTX 备注区，质量门读它）。 */
  notes: "",
}};
"""


def load_spec(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        import yaml  # type: ignore

        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise ValueError(f"Slide Spec root must be an object: {path}")
    return value


def spec_slides(spec: dict[str, Any]) -> list[dict[str, Any]]:
    slides = spec.get("slides") or []
    result: list[dict[str, Any]] = []
    for item in slides:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if number > 0:
            result.append({**item, "id": number})
    result.sort(key=lambda item: int(item["id"]))
    return result


def page_slug(slide: dict[str, Any]) -> str:
    kind = str(slide.get("kind") or "").strip().lower()
    role = str(slide.get("role") or "").strip().lower()
    for token in (kind, role):
        if token in {"cover", "closing", "section", "hook", "toc"}:
            return token
    title = str(slide.get("title") or "")
    parts = re.findall(r"[a-z0-9]+", title.lower())
    if parts:
        return "-".join(parts)[:24]
    return f"s{int(slide['id']):02d}"


def page_filename(slide: dict[str, Any]) -> str:
    return f"p{int(slide['id']):02d}-{page_slug(slide)}.js"


def listed_page_files(pages_dir: Path) -> list[Path]:
    if not pages_dir.is_dir():
        return []
    files = [path for path in pages_dir.glob("p*.js") if PAGE_NAME_RE.match(path.name)]
    files.sort(key=lambda path: int(PAGE_NAME_RE.match(path.name).group(1)))  # type: ignore[union-attr]
    return files


def js_string(value: str) -> str:
    return json.dumps(str(value or ""), ensure_ascii=False)


def _copy_js(slide: dict[str, Any]) -> str:
    """slide_copy / content → JS 字面量。列表嵌数组，标量嵌字符串。"""
    value = slide.get("slide_copy") if slide.get("slide_copy") is not None else slide.get("content")
    if value is None:
        return '""'
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return js_string(str(value))


def _comment_safe(text: Any) -> str:
    """One line, and never able to close the enclosing block comment."""
    return " ".join(str(text or "").replace("*/", "* /").split())


def _on_screen_block(planned: dict[str, Any]) -> str:
    """Spell out this page's verbatim on-screen strings inside the stub.

    2026-09-18 transcript analysis: the stub only said "this page needs its numbers to
    appear", so the builder re-read slide-spec-compiled.yaml 11 times in a single round to
    find out *which* numbers. The strings come from the same function the readback gate
    judges with, so the stub and the gate cannot disagree.
    """
    required = actual_check.planned_requirements(planned)
    lines = [
        "/* ON-SCREEN REQUIRED — the actual-content gate matches PPTX text runs byte-exact",
        "   and reports missing_title / missing_key_claim / planned_numbers_missing.",
        "   Chart data labels are NOT text runs. Render these verbatim:",
    ]
    if required["title"]:
        lines.append(f"   title:   {_comment_safe(required['title'])}")
    if required["claim"]:
        lines.append(f"   claim:   {_comment_safe(required['claim'])}")
    if required["numbers"]:
        lines.append("   numbers: " + " · ".join(_comment_safe(item) for item in required["numbers"]))
    for fragment in required["copy_fragments"][:6]:
        lines.append(f"   copy:    {_comment_safe(fragment)}")
    if required["numbers"]:
        # One carrier per number. Repeating a required number in a second visible place
        # (bar label, big centred figure, second bullet) reads as triple-encoding to the
        # critic; dropping the chart's direct label for a number the text already states
        # is not a defect. 2026-09-17 live: rounds 5-7 oscillated between these two
        # readings, and the last one broke the actual-content gate undoing the other.
        lines.append(
            "   Each number above takes exactly ONE text carrier; do not restate it in a chart "
            "data label or a second bullet, and a bar whose value is already in text needs no "
            "direct label."
        )
    lines.append("*/")
    return "\n".join(lines)


def _pack_sources(work_dir: Path) -> list[dict[str, Any]]:
    """Byte-exact source entries from the work-dir Research Pack.

    2026-09-17 live: the closing page's source titles were hand-typed into a
    repair prompt and drifted at character level (fullwidth quotes), so the
    final-reference gate rejected 6 refs. The scaffold injects the titles
    straight from the pack so no model ever retypes them.
    """
    pack_path = work_dir / "research-pack.json"
    if not pack_path.is_file():
        return []
    try:
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = pack.get("sources") if isinstance(pack, dict) else None
    out: list[dict[str, Any]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        out.append(
            {
                "id": str(entry.get("id") or ""),
                "title": title,
                "publisher": str(entry.get("publisher") or ""),
                "year": entry.get("year"),
            }
        )
    return out


def is_closing_slide(slide: dict[str, Any], slides: list[dict[str, Any]]) -> bool:
    kind = str(slide.get("kind") or "").strip().lower()
    role = str(slide.get("role") or "").strip().lower()
    if kind in {"closing", "references"} or role in {"closing", "references"}:
        return True
    return bool(slides) and slide is slides[-1]


# 深浅三明治的默认分工：cover/hook/section/closing 用 dark companion 压场，
# 内容页用 light 盘保证阅读密度。Builder 可在 renderBackground 调用处覆盖。
DARK_PAGE_KINDS = frozenset({"cover", "hook", "section", "section-divider", "divider", "closing"})


def _visual_payload(slide: dict[str, Any]) -> str:
    """Spec visual → slots.visual 的 JS 字面量（'undefined' 表示无视觉载荷）。"""
    visual = slide.get("visual")
    if isinstance(visual, dict) and visual:
        return json.dumps(visual, ensure_ascii=False)
    return "undefined"


def _archetype_context(slide: dict[str, Any], layout_override: str | None = None) -> str:
    """pptx-layouts.suggestLayouts 的选版式上下文，全部来自冻结 spec。

    reference_analysis 的逐页建议（P2-10）作为 context.layout 覆盖 spec 自身的
    layout 提示——引擎的 +40 分会让建议版式稳赢，但容量/禁忌约束仍然生效。
    """
    visual = slide.get("visual") if isinstance(slide.get("visual"), dict) else {}
    details = visual.get("details") if isinstance(visual.get("details"), dict) else {}
    title = str(slide.get("title") or "")
    copy_value = slide.get("slide_copy") if slide.get("slide_copy") is not None else slide.get("content")
    items = [item for item in (copy_value if isinstance(copy_value, list) else ([copy_value] if copy_value else [])) if item]
    claim = str(slide.get("claim") or "").strip()
    context = {
        "slideId": int(slide["id"]),
        "slideKind": str(slide.get("kind") or "").strip().lower() or None,
        "role": str(slide.get("role") or "").strip().lower() or None,
        "layoutFamily": visual.get("layout_family"),
        "layout": layout_override or slide.get("layout"),
        # claim 会被引擎渲染进 body 区，容量语义上算一个 body item
        # （数据页没有 slide_copy 但 claim 就是 takeaway，body_items≥1 才可行）。
        "itemCount": len(items) + (1 if claim else 0),
        "title": title,
        "titleChars": len(title),
        "hasAsset": bool(visual.get("asset") or details.get("asset")),
        "hasData": bool(visual.get("series") or details.get("series") or details.get("rows")),
        "hasQuote": bool(details.get("quote") or visual.get("quote")),
        "density": str(slide.get("density") or "").strip().lower() or None,
    }
    return json.dumps(context, ensure_ascii=False)


def _page_background(slide: dict[str, Any]) -> tuple[str, str]:
    """(kind, dark) JS 字面量：背景指令页型 + 深浅三明治默认。"""
    kind = str(slide.get("kind") or "").strip().lower() or "content"
    kind_js = json.dumps(kind if kind in {"cover", "content", "section", "closing"} else "content")
    dark_js = "true" if kind in DARK_PAGE_KINDS else "false"
    return kind_js, dark_js


def _source_rail_js(work_dir: Path) -> str:
    sources = _pack_sources(work_dir)
    if not sources:
        return ""
    rendered = json.dumps(sources, ensure_ascii=False, indent=4)
    rendered = rendered.replace("\n", "\n    ")
    return (
        "\n    /* Source rail: byte-exact titles from research-pack.json —"
        "\n       the final-reference gate matches these; render them verbatim"
        "\n       on this page and never retype them. */"
        f"\n    sources: {rendered},"
    )


def write_if_scaffoldable(path: Path, contents: str) -> bool:
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if SCAFFOLD_MARKER not in existing:
            return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    return True


def inline_tokens_json(spec: dict[str, Any], art_direction: Path | None) -> str:
    """Resolved design tokens inlined into deck.js — pages never hand-type colors.

    Same source the palette gate judges against (shared/design_tokens), so the
    scaffolded deck cannot disagree with the gate about what a legal color is.
    calibration_preview.py inlines the same JSON into its harness: the two
    harnesses must never resolve tokens differently (2026-09-28 live).
    """
    root = Path(
        os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parents[2]
    ).resolve()
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from shared.design_tokens import resolve_design_tokens  # noqa: PLC0415

    meta = spec.get("meta") if isinstance(spec.get("meta"), dict) else {}
    style = meta.get("visual_style")
    custom = meta.get("visual_style_custom")
    if art_direction is not None and Path(art_direction).is_file():
        try:
            ad = load_spec(Path(art_direction))
        except ValueError:
            ad = {}
        style = ad.get("style_seed") or ad.get("visual_style") or style
        custom = ad.get("visual_style_custom") or custom
    try:
        tokens = resolve_design_tokens(
            str(style) if style else None,
            custom if isinstance(custom, dict) else None,
        )
    except (OSError, ValueError, KeyError, TypeError):
        tokens = {"palette": {"canvas": "FFFFFF"}}
    return json.dumps(tokens, ensure_ascii=False, indent=2)


def scaffold_generator(
    work_dir: Path,
    spec_path: Path,
    art_direction: Path | None = None,
    reference_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create deck.js + pages/ stubs. Returns counts for the stage summary.

    reference_analysis (P2-10): per-slide archetype suggestions from a good
    reference deck (reference_deck_analysis.py). Suggestions override the
    spec's `layout` hint per page and are counted as `reference_guided`.
    """
    spec = load_spec(spec_path)
    slides = spec_slides(spec)
    suggestions_by_slide: dict[int, str] = {}
    if isinstance(reference_analysis, dict):
        for entry in reference_analysis.get("slides") or []:
            if not isinstance(entry, dict) or not isinstance(entry.get("slide"), int):
                continue
            suggestion = next(
                (
                    item
                    for item in entry.get("suggested_archetypes") or []
                    if isinstance(item, str) and item
                ),
                None,
            )
            if suggestion:
                suggestions_by_slide[int(entry["slide"])] = suggestion
    pages_dir = work_dir / "pages"
    composition_dir = work_dir / "composition"
    composition_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    written_pages = 0
    kept_pages = 0
    reference_guided = 0
    names: list[str] = []
    for slide in slides:
        name = page_filename(slide)
        names.append(name)
        suggestion = suggestions_by_slide.get(int(slide["id"]))
        if suggestion:
            reference_guided += 1
        sources_line = _source_rail_js(work_dir) if is_closing_slide(slide, slides) else ""
        kind_js, dark_js = _page_background(slide)
        stub = PAGE_STUB.format(
            marker=SCAFFOLD_MARKER,
            n=int(slide["id"]),
            # The doc comment is a comment: a spec title containing `*/` must not be able
            # to close it early and turn the rest of the title into code.
            title=_comment_safe(str(slide.get("title") or f"Slide {slide['id']}")),
            title_js=js_string(str(slide.get("title") or f"Slide {slide['id']}")),
            claim_js=js_string(str(slide.get("claim") or "")),
            key_line_js=js_string(str(slide.get("key_line") or "")),
            # slide_copy 可能是列表：嵌成真 JS 数组字面量（str() 会把 Python repr
            # 带引号方括号印到页面上）。字符串走 js_string。
            copy_js=_copy_js(slide),
            sources_line=sources_line,
            on_screen_block=_on_screen_block(slide),
            kind_js=kind_js,
            dark_js=dark_js,
            context_js=_archetype_context(slide, suggestion),
            visual_js=_visual_payload(slide),
        )
        target = pages_dir / name
        if write_if_scaffoldable(target, stub):
            written_pages += 1
        else:
            kept_pages += 1

    requires = ",\n".join(f"  require('./pages/{name}')" for name in names)
    deck = DECK_TEMPLATE.format(
        marker=SCAFFOLD_MARKER,
        requires=requires or "  // no slides",
        tokens_json=inline_tokens_json(spec, art_direction),
    )
    deck_path = work_dir / "deck.js"
    wrote_deck = write_if_scaffoldable(deck_path, deck)
    return {
        "slides": len(slides),
        "written_pages": written_pages,
        "kept_pages": kept_pages,
        "wrote_deck": wrote_deck,
        "pages": names,
        "reference_guided": reference_guided,
    }


def scaffolded_pages(files: list[Path]) -> list[str]:
    """Page modules that still carry the stub marker, i.e. never implemented."""
    return [
        path.name for path in files
        if SCAFFOLD_MARKER in path.read_text(encoding="utf-8")
    ]


def assert_page_split(entry: Path, spec_path: Path) -> None:
    """Refuse a build whose generator is not split one-file-per-slide."""
    spec = load_spec(spec_path)
    slides = spec_slides(spec)
    if not slides:
        raise ValueError("Slide Spec has no slides — cannot build a paged generator")
    expected = {int(item["id"]) for item in slides}
    pages_dir = entry.parent / "pages"
    files = listed_page_files(pages_dir)
    found = {
        int(PAGE_NAME_RE.match(path.name).group(1))  # type: ignore[union-attr]
        for path in files
    }
    if found != expected:
        raise ValueError(
            "pages/ must contain one pNN-*.js per Slide Spec id "
            f"(have {sorted(found)}, need {sorted(expected)}). "
            "Run `ppt_pipeline.py plan` so scaffold can create the stubs."
        )
    text = entry.read_text(encoding="utf-8")
    missing = [path.name for path in files if f"./pages/{path.name}" not in text]
    if missing:
        raise ValueError(
            "deck.js must require every page module; missing "
            + ", ".join(missing)
        )
    unimplemented = scaffolded_pages(files)
    if unimplemented:
        raise ValueError(
            "pages/ still contain the scaffold marker — those pages were never implemented: "
            + ", ".join(unimplemented)
            + ". Implement each page and delete the marker comment before building; "
            "a stub-only deck must not reach build, render or QA."
        )
