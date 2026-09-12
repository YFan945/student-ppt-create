#!/usr/bin/env python3
"""Generate 12x6 style, 36-layout, and 12-page SVG visual smoke galleries."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from contextlib import nullcontext
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pptx_runtime.render import find_pdftoppm, find_soffice
from shared.pptx_static_core import inspect_pptx


def run_checked(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(f"{label} failed\n{result.stdout}\n{result.stderr}")
    return result


def style_deck_source(tokens: dict[str, object]) -> str:
    # style 令牌可能缺 geometry：addTitle 的标题框高度与 safeArea 都依赖
    # safe_margin_pct / title_zone_pct，缺失时标题框只剩 ~0.56in，装不下
    # 32pt 标题行。与 scenario_render_matrix 的 TOKENS 保持同一组默认值。
    tokens = {
        **tokens,
        "geometry": {
            **(tokens.get("geometry") or {}),
            "safe_margin_pct": 6,
            "title_zone_pct": 16,
            "footer_zone_pct": 5,
            "spacing_scale_pt": [6, 12, 18, 24, 36, 48],
            "corner_radius_pt": 8,
        },
    }
    token_json = json.dumps(tokens, ensure_ascii=False)
    style_label = json.dumps(str(tokens["style_name"]), ensure_ascii=False)
    return f"""
const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');
const V = require('pptx-visuals');
const S = require('pptx-shapes');
const SVG = require('pptx-svg-library');
const TOKENS = {token_json};
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
H.applyTokens(pptx, TOKENS, 'chinese');

function baseSlide(mode = 'light', reserveTitle = true) {{
  const tokens = H.paletteMode(TOKENS, mode);
  const slide = pptx.addSlide();
  H.addBackground(slide, tokens);
  const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, tokens, {{ reserveTitle }});
  return {{ slide, tokens, area }};
}}

{{
  const {{ slide, tokens, area }} = baseSlide('light', false);
  H.addTextBox(slide, {style_label}, {{x:area.x,y:area.y+area.h*0.24,w:area.w*0.58,h:area.h*0.24}}, tokens, 'chinese', {{fontSize:34,bold:true,margin:0}});
  H.addFittedText(slide, TOKENS.style_character, {{x:area.x,y:area.y+area.h*0.54,w:area.w*0.74,h:area.h*0.30}}, tokens, 'english', 'caption', {{fontSize:13,color:H.color(tokens,'secondary_text'),margin:0,label:'Style character'}});
  slide.addShape(pptx.ShapeType.ellipse, {{x:area.x+area.w*0.78,y:area.y+area.h*0.20,w:area.h*0.36,h:area.h*0.36,fill:{{color:H.color(tokens,'primary_accent'),transparency:8}},line:{{transparency:100}}}});
}}

{{
  const {{ slide, tokens, area }} = baseSlide('light', false);
  slide.addShape(pptx.ShapeType.arc, {{x:area.x,y:area.y+area.h*0.10,w:area.w*0.24,h:area.h*0.62,adjustPoint:0.35,rotate:12,fill:{{color:H.color(tokens,'secondary_accent'),transparency:36}},line:{{color:H.color(tokens,'primary_accent'),width:1.4}}}});
  H.addFittedText(slide, '02 证据如何成为结论', {{x:area.x+area.w*0.28,y:area.y+area.h*0.20,w:area.w*0.68,h:area.h*0.34}}, tokens, 'chinese', 'title', {{bold:true,label:'章节标题'}});
  H.addFittedText(slide, '从方法进入证据', {{x:area.x+area.w*0.30,y:area.y+area.h*0.64,w:area.w*0.50,h:area.h*0.14}}, tokens, 'chinese', 'caption', {{label:'章节引导'}});
}}

{{
  const {{ slide, tokens, area }} = baseSlide('light', false);
  const stressTitle = '长标题与素材缺失并存时，版式仍须保持清晰';
  // 19 字长标题在 title_min_pt=32 下需要两行：框高必须容纳 2 行（~1.24in），
  // 否则 addFittedText 会在 title 下限处抛错——这正是本用例要守护的边界。
  // 框高同时要满足静态扫描的 0.85 填充上限（37pt 顶格时约需 1.9in）。
  const titleBox = {{x:area.x,y:area.y+area.h*0.04,w:area.w*0.78,h:area.h*0.38}};
  const bodyBox = {{x:area.x,y:area.y+area.h*0.46,w:area.w*0.48,h:area.h*0.30}};
  const visualBox = {{x:area.x+area.w*0.57,y:area.y+area.h*0.46,w:area.w*0.38,h:area.h*0.38}};
  H.addFittedText(slide, stressTitle, titleBox, tokens, 'chinese', 'title', {{bold:true,label:'长标题'}});
  H.addFittedText(slide, '没有可靠素材时，用图表、关系图或留白，不制造纪实感。', bodyBox, tokens, 'chinese', 'body', {{label:'内容策略'}});
  V.renderVisual(slide, 'architecture', {{nodes:['问题','证据','结论']}}, visualBox, tokens, 'chinese');
}}

{{
  const {{ slide, tokens, area }} = baseSlide('light', true);
  H.addTitle(slide, '数据与证据页突出可追溯结论', area, tokens, 'chinese');
  V.renderVisual(slide, 'dashboard', {{title:'方案质量评分', takeaway:'QA 后清晰度提高 21 分。', series:[{{name:'评分', labels:['初稿','精修','QA'], values:[68,84,89]}}]}}, area, tokens, 'chinese');
}}

{{
  const {{ slide, tokens, area }} = baseSlide('light', true);
  H.addTitle(slide, 'SVG 是可选母题，不是视觉配额', area, tokens, 'chinese');
  SVG.addCornerDecoration(slide, TOKENS.svg_reference.name, {{x:area.x+area.w*0.05,y:area.y+area.h*0.10,w:area.w*0.40,h:area.h*0.72}}, tokens);
  H.addFittedText(slide, TOKENS.svg_reference.usage, {{x:area.x+area.w*0.50,y:area.y+area.h*0.16,w:area.w*0.46,h:area.h*0.56}}, tokens, 'english', 'caption', {{fontSize:13,label:'SVG 使用建议'}});
}}

{{
  const {{ slide, tokens, area }} = baseSlide('light', true);
  H.addTitle(slide, '以同一视觉系统完成收束', area, tokens, 'chinese');
  V.renderVisual(slide, 'summary', {{takeaways:['风格有差异','版式可适配','QA 决定完成状态']}}, area, tokens, 'chinese');
}}

pptx.writeFile({{ fileName: process.argv[2] }});
"""


def layout_deck_source(tokens: dict[str, object], registry: dict[str, object]) -> str:
    return f"""
const pptxgen = require('pptxgenjs');
const L = require('pptx-layouts');
const H = require('pptx-helpers');
const V = require('pptx-visuals');
const S = require('pptx-shapes');
const TOKENS = {json.dumps(tokens, ensure_ascii=False)};
const IDS = {json.dumps([item['id'] for item in registry['layouts']], ensure_ascii=False)};
const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
H.applyTokens(pptx, TOKENS, 'chinese');

function addCopy(slide, text, box, options = {{}}) {{
  // 冒烟样例文本：部分版式的小 zone 容不下 node/label 的 16pt 角色下限。
  // 先按调用方角色试排，放不下时降级为 caption（11–12pt 仍可读）；再失败
  // （连 11pt 都放不下）说明是真实版式缺陷，照常抛错。
  const role = options.textRole || 'body';
  try {{
    H.addFittedText(slide, text, box, TOKENS, 'chinese', role, {{fontSize:options.fontSize || 15,bold:Boolean(options.bold),margin:0.08,color:H.color(TOKENS,options.role || 'primary_text'),align:options.align || 'left',valign:options.valign || 'mid',label:options.label || '版式样例文本'}});
  }} catch (error) {{
    if (!(error instanceof RangeError)) throw error;
    H.addFittedText(slide, text, box, TOKENS, 'chinese', 'caption', {{fontSize:options.fontSize || 12,bold:Boolean(options.bold),margin:0.08,color:H.color(TOKENS,options.role || 'primary_text'),align:options.align || 'left',valign:'mid',label:(options.label || '版式样例文本') + '（降级）'}});
  }}
}}

function addPanel(slide, box, label, accent = false, shape = 'roundRect', textRole = 'node') {{
  S.addStyledContainer(slide, shape, box, TOKENS, {{fill:H.color(TOKENS,accent?'secondary_accent':'surface'),fillTransparency:accent?72:4,line:H.color(TOKENS,accent?'primary_accent':'secondary_text')}});
  const inset = S.safeInsetForShape(shape, box);
  addCopy(slide, label, {{x:box.x+inset.x,y:box.y+inset.y,w:box.w-inset.x*2,h:box.h-inset.y*2}}, {{bold:accent,textRole,align:textRole === 'caption' ? 'left' : 'center'}});
}}

function addAbstractVisual(slide, box) {{
  slide.addShape(pptx.ShapeType.rect, {{...box,fill:{{color:H.color(TOKENS,'secondary_accent'),transparency:64}},line:{{color:H.color(TOKENS,'primary_accent'),width:1.2}}}});
  const size = Math.min(box.w, box.h) * 0.28;
  slide.addShape(pptx.ShapeType.ellipse, {{x:box.x+box.w*0.12,y:box.y+box.h*0.18,w:size,h:size,fill:{{color:H.color(TOKENS,'primary_accent'),transparency:12}},line:{{transparency:100}}}});
  slide.addShape(pptx.ShapeType.rect, {{x:box.x+box.w*0.38,y:box.y+box.h*0.45,w:box.w*0.48,h:box.h*0.30,fill:{{color:H.color(TOKENS,'surface'),transparency:8}},line:{{color:H.color(TOKENS,'primary_accent'),width:1}}}});
}}

function renderLayoutSample(slide, layout) {{
  const z = layout.zones;
  const primaryShape = layout.shape_slots[0]?.shape || 'rect';
  if (layout.family === 'cover' || layout.family === 'section') {{
    if (z.body) addCopy(slide, '研究问题：证据如何提升课堂汇报？', z.body, {{bold:true,textRole:'label',align:'center'}});
    if (z.visual) addAbstractVisual(slide, z.visual);
  }} else if (layout.family === 'claim-text') {{
    addPanel(slide, z.body, '结论：完整 QA 后清晰度提升 21 分。', true, primaryShape);
    if (z.visual && layout.id !== 'claim-focus') addPanel(slide, z.visual, '依据：148 页 gallery 完成打包与渲染。');
  }} else if (layout.family === 'visual-image') {{
    addAbstractVisual(slide, z.visual);
    addPanel(slide, z.body, '结构化插图解释关键关系；缺图时不伪造照片。', false, 'pill', 'caption');
  }} else if (layout.family === 'data') {{
    if (layout.id === 'data-kpi-row') {{
      const cells = H.gridLayout(z.visual, 3, 1, {{columnGap:0.12}});
      ['初稿 68','精修 89','提升 +21'].forEach((value,index)=>addPanel(slide,cells[index],value,index===2,['ellipse','pill','hexagon'][index]));
    }} else if (layout.id === 'data-table-highlight') {{
      addPanel(slide, z.visual, '指标      初稿   精修\\n清晰度      68     89\\n证据性      72     91\\n可讲述性    75     88');
    }} else {{
      V.renderVisual(slide, 'dashboard', {{title:'汇报质量评分',takeaway:'完整 QA 后清晰度提升 21 分。',series:[{{name:'评分',labels:['规划','初稿','复核'],values:[68,82,89]}}]}}, z.visual, TOKENS, 'chinese');
    }}
    addCopy(slide, '结论：完整 QA 后，清晰度提升 21 分。', z.body, {{bold:true,textRole:'label',align:'left'}});
  }} else if (layout.family === 'comparison') {{
    if (layout.id === 'compare-criteria') {{
      addPanel(slide, z.body, '维度       固定模板   自适应版式\\n内容适配      弱          强\\n视觉节奏      单一        多样', true);
    }} else {{
      addPanel(slide, z.body, '固定模板\\n生成较快，但长标题和缺图场景容易失衡。', false, primaryShape);
      addPanel(slide, z.visual, '自适应版式\\n先判断容量与素材，再选择构图和视觉 fallback。', true, primaryShape);
    }}
  }} else if (layout.family === 'process-system') {{
    if (layout.id === 'process-vertical') {{
      const cells = H.gridLayout(z.visual, 1, 3, {{rowGap:0.10}});
      ['1 明确结论','2 组织证据','3 渲染复核'].forEach((value,index)=>addPanel(slide,cells[index],value,index===2,layout.shape_slots[index % layout.shape_slots.length]?.shape || 'pill'));
    }} else if (layout.id === 'timeline-roadmap') {{
      const cells = H.gridLayout(z.visual, 4, 1, {{columnGap:0.10}});
      ['1 确认任务','2 选择版式','3 生成页面','4 渲染验收'].forEach((value,index)=>addPanel(slide,cells[index],value,index===3,layout.shape_slots[index % layout.shape_slots.length]?.shape || 'pill'));
    }} else {{
      const family = layout.id === 'architecture-layered' ? 'architecture' : 'process-path';
      const data = family === 'architecture' ? {{nodes:['证据','叙事','页面','复核']}} : {{steps:['结论','证据','页面','复核']}};
      V.renderVisual(slide, family, data, z.visual, TOKENS, 'chinese');
    }}
    if (z.body) addCopy(slide, '步骤标签保持简洁；箭头、编号和空间方向共同表达顺序。', z.body);
  }} else if (layout.id.startsWith('quote-')) {{
    addPanel(slide, z.body, '“设计不是装饰，而是让证据更容易被理解。”\\n— 课堂访谈样例', true);
    if (z.visual && layout.id !== 'quote-focus') addCopy(slide, '解释\\n引文只在有来源且有叙事价值时使用。', z.visual, {{bold:true}});
  }} else if (layout.id === 'references-clean') {{
    V.renderVisual(slide, 'reference', {{references:['教育部（2026）：课堂展示指南','Smith（2025）：Evidence-led Slides','课程访谈记录（2026）']}}, z.body, TOKENS, 'chinese');
    if (z.visual) V.renderVisual(slide, 'reference', {{references:['项目测试报告（2026）','版式 gallery 验收记录（2026）']}}, z.visual, TOKENS, 'chinese');
  }} else {{
    addPanel(slide, z.body, '证据 · 清晰 · 行动', true);
    if (z.visual && !layout.optional_zones.includes('visual')) addCopy(slide, '哪一项证据最能改变判断？', z.visual, {{bold:true,textRole:'label',align:'center'}});
  }}
  addCopy(slide, `${{layout.id}}｜课堂汇报版式`, z.title, {{bold:true,fontSize:18,textRole:'label',align:'left'}});
}}

for (const id of IDS) {{
  const slide = pptx.addSlide();
  H.addBackground(slide, TOKENS);
  const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, TOKENS, {{reserveTitle:true}});
  const layout = L.resolveLayout(id, area);
  renderLayoutSample(slide, layout);
}}
pptx.writeFile({{ fileName: process.argv[2] }});
"""


def svg_atlas_source(tokens: dict[str, object]) -> str:
    return f"""
const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');
const SVG = require('pptx-svg-library');
const TOKENS = {json.dumps(tokens, ensure_ascii=False)};
const NAMES = Object.keys(SVG.CORNER_SETS);
const pptx = new pptxgen();
H.applyTokens(pptx, TOKENS, 'english');
for (const name of NAMES) {{
  const slide = pptx.addSlide();
  H.addBackground(slide, TOKENS);
  const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, TOKENS, {{reserveTitle:false}});
  SVG.addCornerDecoration(slide, name, {{x:area.x+area.w*0.08,y:area.y+area.h*0.08,w:area.w*0.48,h:area.h*0.78}}, TOKENS);
  H.addFittedText(slide, name, {{x:area.x+area.w*0.58,y:area.y+area.h*0.24,w:area.w*0.40,h:area.h*0.30}}, TOKENS, 'english', 'title', {{bold:true,label:'SVG name'}});
  H.addFittedText(slide, SVG.CORNER_SETS[name], {{x:area.x+area.w*0.58,y:area.y+area.h*0.58,w:area.w*0.36,h:area.h*0.14}}, TOKENS, 'english', 'caption', {{label:'SVG motif'}});
}}
pptx.writeFile({{ fileName: process.argv[2] }});
"""


def generate_one(work: Path, name: str, source_text: str, render: bool, expected_pages: int) -> dict[str, object]:
    target_dir = work / name
    target_dir.mkdir(parents=True, exist_ok=True)
    source = target_dir / "gallery.js"
    pptx = target_dir / f"{name}.pptx"
    report = target_dir / "package-report.json"
    source.write_text(source_text, encoding="utf-8")
    run_checked(["node", str(ROOT / "scripts" / "run_with_pptxgenjs.js"), "--output", str(pptx), str(source)], f"{name}: generate")
    run_checked([sys.executable, str(ROOT / "scripts" / "pptx_tool.py"), "validate", str(pptx), "--output", str(report), "--json"], f"{name}: validate")
    static_result = inspect_pptx(pptx)
    if "error" in static_result:
        raise RuntimeError(f"{name}: static QA failed: {static_result['error']}")
    text_overflow = [
        finding
        for finding in static_result.get("findings", [])
        if "text-vertical-overflow-risk" in finding.get("risk", [])
    ]
    if text_overflow:
        pages = sorted({int(item["slide"]) for item in text_overflow})
        raise RuntimeError(f"{name}: static text overflow risks on pages {pages}")
    previews: list[str] = []
    if render:
        render_dir = target_dir / "render"
        run_checked([sys.executable, str(ROOT / "scripts" / "pptx_tool.py"), "render", str(pptx), "--output-dir", str(render_dir), "--prefix", name], f"{name}: render")
        pages = sorted(render_dir.glob(f"{name}-*.png"))
        if len(pages) != expected_pages:
            raise RuntimeError(f"{name}: expected {expected_pages} rendered pages, got {len(pages)}")
        previews = [str(path) for path in pages]
    return {
        "name": name,
        "pptx": str(pptx),
        "package_report": str(report),
        "previews": previews,
        "static_qa": {
            "finding_count": len(static_result.get("findings", [])),
            "text_overflow_count": 0,
        },
    }


def build_gallery(work: Path, render: bool, gallery: str) -> dict[str, object]:
    from shared.design_tokens import resolve_design_tokens

    catalog = json.loads((ROOT / "references" / "design-tokens.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "skills" / "sp-deck" / "references" / "layout-library.json").read_text(encoding="utf-8"))
    results = []
    if gallery in {"styles", "all"}:
        for style_key in sorted(catalog["styles"]):
            tokens = resolve_design_tokens(style_key)
            results.append(generate_one(work, f"style-{style_key}", style_deck_source(tokens), render, 6))
    if gallery in {"layouts", "all"}:
        tokens = resolve_design_tokens("Modern Minimal")
        results.append(generate_one(work, "layouts-36", layout_deck_source(tokens, registry), render, 36))
    if gallery in {"svg", "all"}:
        tokens = resolve_design_tokens("Modern Minimal")
        results.append(generate_one(work, "svg-atlas-12", svg_atlas_source(tokens), render, 12))
    return {
        "ok": True,
        "rendered": render,
        "gallery": gallery,
        "gallery_contract": {
            "styles": "adaptive-freeform visual QA; no catalog ID is shown to the audience",
            "layouts": "internal inspiration and deterministic fallback QA only",
            "svg": "optional toolbox atlas; not a visual quota",
            "style_pages_per_deck": 6,
            "minimum_distinct_style_silhouettes": 5,
        },
        "artifacts": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate style and shared-layout PPTX galleries")
    parser.add_argument("--gallery", choices=("styles", "layouts", "svg", "all"), default="all")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--require-render", action="store_true")
    args = parser.parse_args()
    render_available = bool(find_soffice() and find_pdftoppm())
    if args.require_render and not render_available:
        raise SystemExit("LibreOffice soffice and pdftoppm are required for rendered gallery QA.")
    render = render_available and not args.no_render
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        context = nullcontext(args.output_dir.resolve())
    else:
        context = tempfile.TemporaryDirectory(prefix="sp-visual-system-gallery-")
    with context as location:
        work = Path(location)
        payload = build_gallery(work, render, args.gallery)
        if args.output_dir:
            report_path = work / "gallery-report.json"
            report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            payload["report"] = str(report_path)
        print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
