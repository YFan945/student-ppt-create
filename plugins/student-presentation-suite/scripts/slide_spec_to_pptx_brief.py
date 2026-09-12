#!/usr/bin/env python3
"""Convert a validated Student Presentation Slide Spec into a Claude pptx brief."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.design_tokens import resolve_design_tokens
from shared.handoff_validation import handoff_errors
from shared.runtime_paths import output_root
from shared.slide_spec_validation import semantic_errors


def load_optional_dependencies():
    try:
        import jsonschema
        import yaml
    except ImportError as exc:
        print(
            "Missing dependency. Install Slide Spec dependencies with: "
            "python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(3) from exc
    return jsonschema, yaml


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Slide Spec YAML/JSON and emit a Student Presentation PPTX production brief"
    )
    parser.add_argument("spec", type=Path, help="Slide Spec YAML or JSON file")
    parser.add_argument(
        "--schema",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "references" / "slide-spec.schema.json",
        help="JSON Schema path",
    )
    parser.add_argument("--output", type=Path, help="Markdown brief output path")
    parser.add_argument(
        "--brief",
        type=Path,
        help="Optional Presentation Brief to validate against the Slide Spec",
    )
    parser.add_argument(
        "--production-mode",
        choices=("create", "edit_ooxml", "rebuild_from_source"),
        help="Explicit production mode selected after source inspection",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Deliverable directory; defaults to CLAUDE_PROJECT_DIR/outputs or cwd/outputs",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON metadata instead of Markdown")
    return parser.parse_args()


def load_spec(path: Path, yaml_module: Any) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml_module.safe_load(text)


def validate_spec(data: Any, schema_path: Path, jsonschema_module: Any) -> list[dict[str, str]]:
    """校验内存中的 spec 对象并返回规范化错误列表。

    与 ``shared.slide_spec_contract.validate_slide_spec``（按路径加载并附加文件哈希）
    共用同一套 schema + ``semantic_errors`` 逻辑；本函数针对已在内存中构造的输入
    （例如场景矩阵预生成的 spec 对象），不重复从磁盘加载。两者应保持一致，避免
    错误形状与语义错误附加方式漂移。
    """
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema_module.Draft202012Validator.check_schema(schema)
    validator = jsonschema_module.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
    errors = [
        {
            "path": "." + ".".join(str(part) for part in error.path),
            "message": error.message,
        }
        for error in errors
    ]
    if not errors:
        errors.extend(semantic_errors(data))
    return errors


def text_block(value: Any, indent: str = "") -> str:
    if isinstance(value, str):
        return indent + value
    if isinstance(value, list):
        return "\n".join(f"{indent}- {text_block(item).strip()}" for item in value)
    if isinstance(value, dict):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{indent}- {key}:")
                lines.append(text_block(item, indent + "  "))
            else:
                lines.append(f"{indent}- {key}: {item}")
        return "\n".join(lines)
    return indent + str(value)


def meta_value(meta: dict[str, Any], key: str, default: str = "not specified") -> Any:
    value = meta.get(key)
    if value in (None, "", []):
        return default
    return value


def derive_production_mode(data: dict[str, Any], requested: str | None = None) -> str:
    """Derive and validate the production mode without treating every finding as an edit."""
    source_value = data.get("source_deck")
    source = Path(str(source_value)).expanduser() if source_value else None
    suffix = source.suffix.casefold() if source else ""
    editable = suffix in {".pptx", ".potx"}
    view_only = suffix in {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    intent = data.get("edit_intent")

    if requested:
        if requested == "edit_ooxml" and not editable:
            raise ValueError("edit_ooxml requires source_deck ending in .pptx or .potx")
        if requested == "edit_ooxml" and source and source.exists() and not zipfile.is_zipfile(source):
            raise ValueError("edit_ooxml source_deck is not a readable PPTX/POTX package")
        if requested == "create" and editable:
            raise ValueError("create cannot silently replace an editable source deck; use edit_ooxml or rebuild_from_source")
        if requested == "rebuild_from_source" and not source:
            raise ValueError("rebuild_from_source requires source_deck")
        return requested

    if intent == "rebuild-clean-copy":
        if not source:
            raise ValueError("rebuild-clean-copy requires source_deck")
        return "rebuild_from_source"
    if editable:
        if source and source.exists() and not zipfile.is_zipfile(source):
            return "rebuild_from_source"
        return "edit_ooxml"
    if view_only or not source:
        return "create"
    return "rebuild_from_source"


def validate_production_source(data: dict[str, Any], mode: str) -> None:
    """Require a readable local source whenever production consumes one."""
    source_value = data.get("source_deck")
    if mode not in {"edit_ooxml", "rebuild_from_source"}:
        return
    if not source_value:
        raise ValueError(f"{mode} requires source_deck")
    source = Path(str(source_value)).expanduser()
    if not source.is_file():
        raise ValueError(f"{mode} source_deck is not a readable local file: {source}")
    if mode == "edit_ooxml" and not zipfile.is_zipfile(source):
        raise ValueError("edit_ooxml source_deck is not a readable PPTX/POTX package")


def _estimate_slide_text_fit(
    slides: list[dict[str, Any]],
    meta: dict[str, Any],
) -> list[dict[str, Any]]:
    """预估每页内容在最小字号下是否会溢出典型文本框。

    返回有溢出风险的幻灯片列表（不含正常的幻灯片）。
    """
    lang = str(meta.get("language", "")).lower()
    is_cjk = lang in ("chinese", "bilingual")
    font_size = 22 if is_cjk else 20  # 最小正文字号

    # 典型文本框尺寸（16:9 幻灯片，安全区域内）
    typical_width_cm = 22.0   # 典型内容区宽度
    typical_height_cm = 10.5  # 典型内容区高度（扣除标题栏和边距）
    # 中文 ≈ 字号×0.035, 英文 ≈ 字号×0.021
    char_width_cm = font_size * (0.035 if is_cjk else 0.021)
    chars_per_line = max(1, int(typical_width_cm / char_width_cm))
    line_height_cm = font_size * 1.4 / 72 * 2.54
    safe_height_cm = typical_height_cm * 0.85

    warnings: list[dict[str, Any]] = []
    for slide in slides:
        content = slide.get("content") or {}
        slide_copy = slide.get("slide_copy") or ""
        # 计算内容字符数
        chars = 0
        if isinstance(content, dict):
            bullets = content.get("bullets", content.get("text", []))
            chars = (
                sum(len(str(bullet)) for bullet in bullets)
                if isinstance(bullets, list)
                else len(str(content))
            )
        elif isinstance(content, str):
            chars = len(content)
        if not chars and slide_copy:
            chars = len(str(slide_copy))
        if chars <= 20:  # 极短内容无需检查
            continue

        est_lines = (chars + chars_per_line - 1) // chars_per_line
        text_height = est_lines * line_height_cm
        overflow_fill = text_height / typical_height_cm if typical_height_cm > 0 else 0

        if text_height > safe_height_cm:
            warnings.append({
                "slide_id": slide.get("id"),
                "title": slide.get("title", "")[:50],
                "chars": chars,
                "est_lines": est_lines,
                "text_height_cm": round(text_height, 1),
                "fill_ratio_pct": round(overflow_fill * 100),
                "recommendation": (
                    "文字量可能超出典型文本框。建议：(1) 拆分幻灯片 "
                    f"(2) 精简内容至 ~{int(chars_per_line * 4)} 字以内 "
                    "(3) 将解释移至讲稿"
                ),
            })
    return warnings


def build_brief(
    data: dict[str, Any],
    source: Path,
    deliverable_dir: Path | None = None,
    production_mode: str | None = None,
) -> str:
    meta = data.get("meta") or {}
    slides = data["slides"]
    output_prefix = meta.get("output_prefix") or source.stem
    resolved_output_dir = output_root(deliverable_dir)
    pptx_path = resolved_output_dir / f"{output_prefix}-presentation.pptx"
    notes_path = resolved_output_dir / f"{output_prefix}-speaker-notes.md"
    preview_path = resolved_output_dir / f"{output_prefix}-preview.png"
    change_summary_path = resolved_output_dir / f"{output_prefix}-change-summary.md"
    quality_report_path = resolved_output_dir / f"{output_prefix}-quality-report.json"
    teleprompter_path = resolved_output_dir / f"{output_prefix}-teleprompter.html"
    revision_manifest_path = resolved_output_dir / f"{output_prefix}-revision-manifest.json"
    delivery_report_path = resolved_output_dir / f"{output_prefix}-delivery-report.json"
    total_timing = sum(int(slide.get("timing_sec", 0)) for slide in slides)
    members = meta.get("members") or []
    member_text = ", ".join(members) if members else "not specified"
    review_findings = data.get("review_findings") or []
    preserve = data.get("preserve") or []
    is_improvement = bool(
        data.get("source_deck")
        or data.get("edit_intent")
        or review_findings
        or data.get("change_summary_required")
        or data.get("revision_operation")
    )
    production_mode = derive_production_mode(data, production_mode)
    design_tokens = resolve_design_tokens(
        meta.get("visual_style"), meta.get("visual_style_custom")
    )

    lines = [
        "# Claude PPTX Production Brief",
        "",
        "Use the suite-owned PPTX runtime to create or edit the editable PPTX.",
        "This brief is generated from a validated Student Presentation Slide Spec.",
        "",
        "## Production Mode",
        f"- Mode: `{production_mode}`",
        "- Workflow: `references/pptx-production.md`",
        "- Runtime commands: `references/pptx-runtime.md`",
        "- Create safety: `references/pptxgenjs-safety.md`",
        "- Existing-deck editing: `references/pptx-editing.md`",
        "- QA and completion: `references/pptx-qa.md`",
        "",
        "## Runtime Contract",
        "",
        "Create/rebuild mode writes a pptxgenjs `deck.js` following `pptxgenjs-safety.md`;",
        "compose each slide adaptively from its task and assets. Use `pptx-helpers.js` for safety;",
        "treat `pptx-layouts.js`, composer, SVG, shape, and visual libraries as optional inspiration",
        "or deterministic fallback. A slide layout is exact only when `layout_lock: true`. Edit",
        "mode uses only `pptx_tool.py` and must preserve the source package. Do not duplicate",
        "runtime implementation or helper documentation inside this data brief.",
        "",
        "## Output Contract",
        f"- Project output directory: `{resolved_output_dir}`",
        f"- PPTX: `{pptx_path}`",
        f"- Notes: `{notes_path}`",
        f"- Preview/contact sheet: `{preview_path}` or a contact sheet in the same directory",
        f"- Delivery report: `{delivery_report_path}`",
    ]
    if production_mode == "edit_ooxml":
        toolkit_start = lines.index("## Runtime Contract")
        output_contract = lines.index("## Output Contract")
        lines[toolkit_start:output_contract] = [
            "## Editing Runtime",
            "",
            "Use `pptx_tool.py` for inspect, thumbnail, unpack, structural edits, clean, pack, and validate.",
            "Do not generate `deck.js`, rebuild the deck with pptxgenjs, or overwrite the source package.",
            "Preserve theme, masters, layouts, notes, relationships, embedded media, and unrelated slides.",
            "",
        ]
    export_formats = meta.get("export_formats") or meta.get("deliverables") or []
    if "pdf" in export_formats:
        lines.append(f"- PDF: `{resolved_output_dir / f'{output_prefix}-presentation.pdf'}`")
    if "teleprompter" in export_formats:
        lines.append(f"- Teleprompter: `{teleprompter_path}`")
    if "quality-report" in export_formats:
        lines.append(f"- Quality report: `{quality_report_path}`")
    if meta.get("versioning") or "revision-manifest" in export_formats:
        lines.append(f"- Revision manifest: `{revision_manifest_path}`")
    if is_improvement or data.get("change_summary_required"):
        lines.append(f"- Change summary: `{change_summary_path}`")
    lines.extend(
        [
            "",
            "## Deck Constraints",
            f"- Topic: {meta_value(meta, 'topic')}",
            f"- Presentation type: {meta_value(meta, 'presentation_type')}",
            f"- Scenario: {meta_value(meta, 'scenario')}",
            f"- Audience: {meta_value(meta, 'audience')}",
            f"- Audience type/depth: {meta_value(meta, 'audience_type')} / {meta_value(meta, 'audience_depth')}",
            f"- Language: {meta_value(meta, 'language')}",
            f"- Duration minutes: {meta_value(meta, 'duration_min')}",
            f"- Slide count: {meta.get('slide_count') or len(slides)}",
            f"- Total scripted timing seconds: {total_timing}",
            f"- Format: {meta_value(meta, 'format')}",
            f"- Members: {member_text}",
            f"- Course: {meta_value(meta, 'course')}",
            f"- Rubric: {meta_value(meta, 'rubric')}",
            f"- Structure mode: {meta_value(meta, 'structure_mode')}",
            f"- Interaction mode: {meta_value(meta, 'interaction_mode')}",
            f"- Quality level: {meta_value(meta, 'quality_level')}",
            f"- Maximum slide words: {meta_value(meta, 'max_words_per_slide')}",
            f"- Maximum Chinese slide characters: {meta_value(meta, 'max_chinese_chars_per_slide')}",
            f"- Visual/text ratio: {meta_value(meta, 'visual_text_ratio')}",
            f"- Citation style: {meta_value(meta, 'citation_style')}",
            "- Source material:",
            text_block(meta.get("source_material") or ["not specified"], "  "),
            f"- Template: {meta_value(meta, 'template')}",
            f"- Logo: {meta_value(meta, 'logo')}",
            f"- Image source policy: {meta_value(meta, 'image_source')}",
            f"- Visual style: {meta_value(meta, 'visual_style')}",
            f"- Custom visual reference: {json.dumps(meta.get('visual_style_custom'), ensure_ascii=False) if meta.get('visual_style_custom') else 'not applicable'}",
            "- Required deliverables:",
            text_block(
                meta.get("deliverables")
                or ["pptx", "speaker-notes", "preview"],
                "  ",
            ),
        ]
    )
    lines.extend(
        [
            "",
            "## Resolved Design Tokens",
            "Geometry, typography minima, palette roles, and contrast are safety constraints. "
            "Style character, background treatments, and SVG reference are lightweight suggestions; "
            "they do not choose layouts, shapes, image treatment, charts, components, or page rhythm.",
            "```json",
            json.dumps(design_tokens, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    if design_tokens.get("custom_style"):
        lines.append("- Custom visual reference: use the confirmed four-part reference above and retain shared safety rules.")
    if is_improvement:
        lines.extend(
            [
                "",
                "## Existing Deck Improvement Contract",
                f"- Source deck/artifact: {data.get('source_deck') or 'not specified'}",
                f"- Edit intent: {data.get('edit_intent') or 'review-fix'}",
                f"- Production mode: `{production_mode}`. Follow `references/pptx-editing.md` unless the explicit mode is `rebuild_from_source`.",
                "- Do not overwrite the source deck; write a separate improved PPTX.",
                "- Preserve:",
                text_block(preserve or ["template/logo/footer/source citations unless the spec says otherwise"], "  "),
                "- Review findings to apply:",
            ]
        )
        for finding in review_findings:
            lines.append(
                f"  - {finding.get('severity', 'Major')}, {finding.get('target', 'deck')}: "
                f"{finding.get('problem', 'problem not specified')} "
                f"Fix: {finding.get('fix', 'fix not specified')}"
            )
        if not review_findings:
            lines.append(
                "  - No structured findings supplied; infer fixes from the conversation and source deck evidence."
            )
    if data.get("revision_operation"):
        lines.extend(
            [
                "",
                "## Scoped Revision Contract",
                f"- Operation: {data.get('revision_operation')}",
                f"- Target slides: {', '.join(str(item) for item in data.get('target_slides') or []) or 'not specified'}",
                f"- Target section: {data.get('target_section') or 'not specified'}",
                "- Do not change slides outside this scope, and never change a locked slide without explicit unlock approval.",
            ]
        )
    lines.extend(
        [
            "",
            "## Student Presentation Requirements",
            "- Keep one clear message per content slide; use claim-style titles for argumentative and evidence slides.",
            "- Chinese normal body text must be >= 22pt; English normal body text must be >= 20pt.",
            "- Primary slide titles should normally be >= 24pt; visually verify smaller secondary labels.",
            "- Text must fit its container at minimum font sizes. If content is too long: split slides or "
            "move explanation to speaker notes. Never shrink below minimums to make text fit.",
            "- Use functional visual structures when they clarify content; do not force decoration onto covers, dividers, references, appendix, or Q&A slides.",
            "- Avoid generic AI-sounding filler; prefer course/project-specific examples and modest claims.",
            "- Include speaker notes or a separate notes file with note goals and transitions.",
        ]
    )

    # 文字适配预警
    overflow_warnings = _estimate_slide_text_fit(slides, meta)
    if overflow_warnings:
        lines.extend(
            [
                "",
                "## ⚠ Text Fit Warnings (Review Before Production)",
                "The following slides may overflow typical text boxes at minimum font sizes.",
                "Resolve these BEFORE writing pptxgenjs code:",
                "",
            ]
        )
        for w in overflow_warnings:
            lines.append(
                f"- **Slide {w['slide_id']}** ({w['title']}): "
                f"{w['chars']} 字符 → 约 {w['est_lines']} 行 / {w['text_height_cm']}cm "
                f"({w['fill_ratio_pct']}% 盒高)。{w['recommendation']}"
            )
    else:
        lines.extend(
            [
                "",
                "## ✓ Text Fit Check Passed",
                "No slide exceeds the typical text-box capacity at minimum font sizes.",
            ]
        )

    plan_title = "## Slide Edit Plan" if production_mode == "edit_ooxml" else "## Slide Plan"
    plan_instruction = (
        "Map every target to the inspected source slide; record preserved and changed elements."
        if production_mode == "edit_ooxml"
        else "Implement each confirmed slide with the helper and safety contracts referenced above."
    )
    lines.extend(["", plan_title, "", plan_instruction, "", "---"])
    for slide in slides:
        visual = slide.get("visual") or {}
        kind = slide.get("kind", "content")
        slide_copy = slide.get("slide_copy") or ""
        claim = slide.get("claim", "")

        if production_mode == "edit_ooxml":
            code_hint = (
                "**edit action**: inspect the mapped source slide, change only confirmed targets, "
                "and preserve unrelated OOXML parts and relationships"
            )
        elif slide_copy and len(slide_copy) > 80:
            code_hint = (
                "**production action**: text-fit risk; split or shorten content instead of "
                "shrinking below the confirmed minimum font size"
            )
        else:
            code_hint = (
                "**production action**: implement this slide with the confirmed design tokens "
                "and the referenced helper/safety contract"
            )

        lines.extend(
            [
                "",
                f"### Slide {slide['id']}: {slide['title']}",
                f"- Slide kind: {kind}",
                f"- Layout intent: {slide['layout']}",
                f"- Layout behavior: {'locked exact composition' if slide.get('layout_lock') else 'adaptive hint; proportions, shapes, zones, and composition may change'}",
                f"- Story role: {slide.get('role', 'not specified')}",
                f"- Claim: {claim or 'not specified'}",
                f"- Owner: {slide['owner']} / Timing: {slide['timing_sec']}s",
                f"- {code_hint}",
                "- Supporting points:",
                text_block(slide.get("supporting_points") or ["not specified"], "  "),
                f"- Visual: type={visual.get('type', 'none')}, purpose={visual.get('purpose', 'none')}",
                "- Content:",
                text_block(slide["content"], "  "),
                "- PPT copy:",
                text_block(slide_copy or ["derive from content within confirmed density limits"], "  "),
                f"- Speaker note goal: {slide.get('note_goal', 'not required')}",
                f"- Speaker notes: {slide.get('speaker_notes', 'generate from note goal and evidence')}",
                f"- Key line: {slide.get('key_line', 'not required')}",
                f"- Evidence refs: {', '.join(slide.get('evidence_refs') or []) or 'not specified'}",
                f"- Locked: {bool(slide.get('locked'))}",
                f"- Transition: {slide.get('transition', 'not required')}",
            ]
        )

    lines.extend(
        [
            "",
            "## Required QA",
            f"- Run `python \"${{CLAUDE_PLUGIN_ROOT}}/scripts/analyze_presentation_spec.py\" <spec> --output \"{quality_report_path}\" --strict --json` before final production.",
            "- Run `pptx_tool.py inspect --text-output` for every final candidate and compare the extracted text, order, and placeholders with the validated Slide Spec.",
            "- Reuse the producing-stage package report when its PPTX hash still matches; otherwise run `python \"${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py\" validate <pptx> --output <package-report.json> --json`. Source-derived decks add `--original <source>`.",
            "- 视觉 QA（渲染能力可用时，以 `check_claude_pptx_env.py` 判定）：Run `python \"${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py\" render <pptx> --output-dir <render-dir> --prefix <topic>`, then inspect every rendered page once. Repair and rerun only when the first candidate has a blocker.",
            "- 无渲染能力时 delivery 以 `--allow-missing-preview` 生成 `incomplete` 报告；不能转 complete，补渲染后经 `incomplete → qa` 恢复边重入 QA。",
            "- Validate the final PPTX package, render every page, and inspect every preview. Normal tasks do not create separate content/asset/visual manifests.",
            f"- After the visual review, author `visual-review.json` bound to the final PPTX (`pptx_sha256` + one entry per slide), then run `python \"${{CLAUDE_PLUGIN_ROOT}}/skills/sp-deck/scripts/pptx_delivery_check.py\" --simple --strict --visual-reviewed --visual-review-report <visual-review.json> --pptx <pptx> --slide-spec-report <slide-spec-report.json> --notes <notes> --preview <page.png> --package-report <package-report.json> --output \"{delivery_report_path}\" --json`. A bare `--visual-reviewed` flag without the sha256-bound report does not pass the simplified gate.",
            f"- Transition to complete with `workflow_guard.py transition --to complete --pptx <pptx> --delivery-report \"{delivery_report_path}\"`.",
            f"- For existing deck improvements, verify `{change_summary_path}` lists kept content, changed slides, unresolved risks, and QA results.",
            f"- When versioning is enabled, store the versioned package under `{resolved_output_dir / 'versions'}` and write `{revision_manifest_path}`.",
            "- Final response must report file existence, slide count, package validation, visual QA status, and limitations.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    jsonschema, yaml = load_optional_dependencies()
    try:
        data = load_spec(args.spec, yaml)
        errors = validate_spec(data, args.schema, jsonschema)
        if not errors and args.brief:
            brief_data = load_spec(args.brief, yaml)
            brief_schema = json.loads(
                (ROOT / "references" / "presentation-brief.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            brief_validator = jsonschema.Draft202012Validator(brief_schema)
            for error in sorted(
                brief_validator.iter_errors(brief_data),
                key=lambda item: tuple(str(part) for part in item.path),
            ):
                location = ".brief" + "".join(f"[{part!r}]" for part in error.path)
                errors.append({"path": location, "message": error.message})
            if not errors:
                errors.extend(handoff_errors(brief_data, data))
        if not errors:
            production_mode = derive_production_mode(data, args.production_mode)
            validate_production_source(data, production_mode)
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError, jsonschema.SchemaError) as exc:
        result = {"valid": False, "error": str(exc), "errors": []}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"Slide Spec conversion failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    if errors:
        result = {"valid": False, "error_count": len(errors), "errors": errors}
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print("Slide Spec is invalid:", file=sys.stderr)
            for error in errors:
                print(f"- {error['path']}: {error['message']}", file=sys.stderr)
        raise SystemExit(1)

    deliverable_dir = output_root(args.output_dir)
    brief = build_brief(data, args.spec, deliverable_dir, args.production_mode)
    result = {
        "valid": True,
        "slide_count": len(data["slides"]),
        "output_dir": str(deliverable_dir),
        "output": str(args.output) if args.output else None,
        "brief": brief,
        "production_mode": derive_production_mode(data, args.production_mode),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(brief, encoding="utf-8")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not args.output:
        print(brief)
    else:
        print(f"Wrote Claude pptx brief: {args.output}")


if __name__ == "__main__":
    main()
