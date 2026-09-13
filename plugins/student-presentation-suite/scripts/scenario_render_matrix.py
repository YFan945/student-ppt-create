#!/usr/bin/env python3
"""Generate, render, and strictly validate representative student PPTX scenarios.

Generated artifacts remain in a temporary directory.  CI should invoke this with
``--require-render`` on a runner that has LibreOffice and Poppler installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.pptx_runtime.render import find_pdftoppm, find_soffice
from shared.slide_spec_validation import semantic_errors

MATRIX = {
    "coursework-zh": ("coursework", "Chinese", ["background", "method", "evidence", "conclusion"]),
    "english-class": ("coursework", "English", ["background", "method", "evidence", "conclusion"]),
    "defense-zh": ("defense", "Chinese", ["problem", "method", "result", "value", "limitation", "qa"]),
    "competition-zh": ("competition", "Chinese", ["problem", "solution", "method", "result", "value", "limitation"]),
    "club-bilingual": ("club-showcase", "bilingual", ["opening", "method", "result", "value"]),
    "research-zh": ("research", "Chinese", ["problem", "background", "method", "result", "limitation", "conclusion"]),
    "software-project": ("coursework", "Chinese", ["problem", "method", "evidence", "conclusion"]),
    "data-survey": ("research", "Chinese", ["problem", "background", "method", "result", "limitation", "conclusion"]),
    "school-template-edit": ("coursework", "Chinese", ["background", "method", "evidence", "conclusion"]),
}

VISUAL_RECIPES = (
    (
        "comparison",
        "comparison",
        {"items": ["Current", "Target"], "dimensions": ["clarity", "evidence"]},
    ),
    (
        "process",
        "process-path",
        {"steps": ["Frame", "Build", "Verify"]},
    ),
    (
        "chart",
        "dashboard",
        {
            "measure": "quality score",
            "unit": "points",
            "scope": "scenario matrix",
            "source": "generated fixture",
            "takeaway": "the runtime completes the scenario",
            "title": "Scenario quality",
            "series": [
                {
                    "name": "Score",
                    "labels": ["Plan", "Produce", "QA"],
                    "values": [72, 88, 96],
                }
            ],
            "metrics": [
                {"value": "3", "label": "stages"},
                {"value": "1", "label": "candidate"},
                {"value": "0", "label": "blockers"},
            ],
        },
    ),
    (
        "matrix",
        "matrix",
        {
            "items": [
                {"label": "Content", "x": 0.25, "y": 0.7},
                {"label": "Visual", "x": 0.55, "y": 0.85},
                {"label": "QA", "x": 0.8, "y": 0.6},
            ]
        },
    ),
    (
        "architecture",
        "architecture",
        {"nodes": ["Spec", "Generator", "PPTX", "QA"]},
    ),
    (
        "timeline",
        "timeline",
        {"stages": ["Plan", "Produce", "Render", "Deliver"]},
    ),
    (
        "hero",
        "hero",
        {"title": "Scenario checkpoint", "subtitle": "One claim, one visual focus"},
    ),
    (
        "diagram",
        "visual-dominant",
        {"annotations": ["Subject", "Evidence", "Takeaway"]},
    ),
    (
        "quote",
        "quote",
        {"quote": "Clear visuals verify.", "source": "Fixture"},
    ),
    (
        "summary",
        "summary",
        {"takeaways": ["Plan", "Generate", "Verify"]},
    ),
    (
        "reference",
        "reference",
        {"references": ["Scenario fixture (2026)", "Suite runtime documentation"]},
    ),
)


def recipe_for(name: str, index: int) -> tuple[str, str, dict[str, object]]:
    if name == "school-template-edit" and index == 2:
        return VISUAL_RECIPES[2]
    offset = sum(name.encode("utf-8")) % len(VISUAL_RECIPES)
    return VISUAL_RECIPES[(offset + index) % len(VISUAL_RECIPES)]


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


def exercise_adaptive_composition_contracts() -> list[str]:
    """Exercise freeform, hint, lock, and deterministic fallback semantics."""
    node_path = os.pathsep.join((str(ROOT / "scripts"), str(ROOT / "node_modules")))
    script = r"""
require('module').Module._initPaths();
const C=require('pptx-composer');
const tokens={geometry:{safe_margin_pct:6,footer_zone_pct:5,title_zone_pct:16},palette:{primary_accent:'2563EB'},typography:{title_min_pt:24,body_cjk_min_pt:22,body_latin_min_pt:20,caption_min_pt:10,title_font:'Cambria',body_font:'Calibri'}};
const base={id:1,title:'Composition contract',kind:'content',layout:'claim-evidence',content:['Evidence','Implication']};
const adaptive=C.resolveSlideComposition(base,{tokens,history:[]});
if(adaptive.exact || adaptive.zones || adaptive.suggestions.length < 2) throw new Error('adaptive-freeform contract failed');
const hint=C.resolveSlideComposition({...base,layout:'visual-left'},{tokens,history:[]});
if(hint.exact || hint.layout_hint !== 'visual-left') throw new Error('unlocked hint contract failed');
const locked=C.resolveSlideComposition({...base,layout_lock:true},{tokens,history:[]});
if(!locked.exact || locked.id !== 'claim-evidence' || !locked.zones) throw new Error('layout lock contract failed');
const fallback=C.resolveSlideComposition(base,{tokens,history:[],compositionMode:'deterministic-fallback'});
if(!fallback.exact || !fallback.zones) throw new Error('deterministic fallback contract failed');
console.log(JSON.stringify({ok:true}));
"""
    env = os.environ.copy()
    env["NODE_PATH"] = node_path
    result = subprocess.run(
        ["node", "-e", script],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode:
        raise RuntimeError(f"adaptive composition contracts failed\n{result.stdout}\n{result.stderr}")
    return [
        "adaptive-freeform",
        "layout-hint-unlocked",
        "layout-locked",
        "freeform-deterministic-fallback",
    ]


def generate_deck(work: Path, name: str, language: str, roles: list[str]) -> Path:
    deck = work / f"{name}.js"
    pptx = work / f"{name}-presentation.pptx"
    role_json = json.dumps(roles, ensure_ascii=False)
    recipes_json = json.dumps(
        [
            {
                "family": recipe_for(name, index)[1],
                **recipe_for(name, index)[2],
            }
            for index in range(len(roles))
        ],
        ensure_ascii=False,
    )
    deck.write_text(f"""
const pptxgen = require('pptxgenjs');
const H = require('pptx-helpers');
const V = require('pptx-visuals');
const TOKENS = {{
  palette: {{ canvas: 'F8FAFC', primary_text: '111827', secondary_text: '4B5563' }},
  typography: {{ title_min_pt: 24, body_cjk_min_pt: 22, body_latin_min_pt: 20,
                 title_font: 'Cambria', body_font: 'Calibri' }},
  geometry: {{ safe_margin_pct: 6, title_zone_pct: 16, footer_zone_pct: 5,
               spacing_scale_pt: [6, 12, 18, 24, 36, 48], corner_radius_pt: 8 }}
}};
const pptx = new pptxgen();
H.applyTokens(pptx, TOKENS, '{language.lower()}');
const roles = {role_json};
const recipes = {recipes_json};
for (const [index, role] of roles.entries()) {{
  const slide = pptx.addSlide(); slide.background = {{ color: 'F8FAFC' }};
  const area = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, TOKENS);
  H.addTitle(slide, `${{index + 1}}. ${{role}}`, area, TOKENS, '{language.lower()}');
  V.renderVisual(slide, recipes[index].family, recipes[index], area, TOKENS, '{language.lower()}');
  if ({json.dumps(name)} === 'school-template-edit') slide.addNotes(`Speaker note for ${{role}}`);
}}
pptx.writeFile({{ fileName: process.argv[2] }});
""", encoding="utf-8")
    subprocess.run(
        [
            "node",
            str(ROOT / "scripts" / "run_with_pptxgenjs.js"),
            "--output",
            str(pptx),
            str(deck),
        ],
        check=True,
    )
    return pptx


def exercise_school_template_edit(work: Path, tool: Path, source: Path) -> tuple[Path, str]:
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    text_output = work / "school-template-source-text.md"
    run_checked(
        [sys.executable, str(tool), "inspect", str(source), "--text-output", str(text_output)],
        "school-template-edit: inspect",
    )
    run_checked(
        [
            sys.executable,
            str(tool),
            "thumbnail",
            str(source),
            "--output-prefix",
            str(work / "school-template-source-thumb"),
        ],
        "school-template-edit: thumbnail",
    )
    unpacked = work / "school-template-unpacked"
    run_checked(
        [sys.executable, str(tool), "unpack", str(source), "--output", str(unpacked)],
        "school-template-edit: unpack",
    )
    slide_xml = unpacked / "ppt" / "slides" / "slide1.xml"
    original_xml = slide_xml.read_text(encoding="utf-8")
    edited_xml = original_xml.replace("background", "background edited", 1)
    if edited_xml == original_xml:
        raise RuntimeError("school-template-edit: fixture title was not found in slide XML")
    slide_xml.write_text(edited_xml, encoding="utf-8")
    run_checked(
        [sys.executable, str(tool), "clean", str(unpacked)],
        "school-template-edit: clean",
    )
    target = work / "school-template-edit-edited-presentation.pptx"
    run_checked(
        [sys.executable, str(tool), "pack", str(unpacked), "--output", str(target)],
        "school-template-edit: pack",
    )
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("school-template-edit: source deck changed during edit workflow")
    return target, source_hash


def exercise_rendered_review(
    work: Path, tool: Path, source: Path, expected_pages: int
) -> None:
    """Exercise the review-owned static scan plus independent render path."""
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    static_check = ROOT / "skills" / "sp-review" / "scripts" / "pptx_static_check.py"
    run_checked(
        [sys.executable, str(static_check), str(source), "--json"],
        "review-rendered: static scan",
    )
    render_dir = work / "review-rendered-previews"
    run_checked(
        [
            sys.executable,
            str(tool),
            "render",
            str(source),
            "--output-dir",
            str(render_dir),
            "--prefix",
            "review-rendered",
        ],
        "review-rendered: render",
    )
    if len(list(render_dir.glob("review-rendered-*.png"))) != expected_pages:
        raise RuntimeError("review-rendered: preview coverage is incomplete")
    if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("review-rendered: source deck changed during read-only review")


def validate_scenario(
    work: Path,
    name: str,
    scenario: str,
    language: str,
    roles: list[str],
) -> tuple[Path, Path, Path]:
    data = {
        "schema_version": "2.0",
        "meta": {
            "scenario": scenario,
            "language": language,
            "slide_count": len(roles),
            "visual_text_ratio": "balanced",
        },
        "slides": [
            {
                "id": index + 1,
                "title": f"{index + 1}. {role}",
                "layout": recipe_for(name, index)[1],
                "content": role,
                "role": role,
                "timing_sec": 30,
                "owner": "A",
                "visual": {
                    "type": recipe_for(name, index)[0],
                    "purpose": f"Exercise the {role} visual structure",
                    "layout_family": recipe_for(name, index)[1],
                    "details": recipe_for(name, index)[2],
                },
            }
            for index, role in enumerate(roles)
        ],
    }
    errors = semantic_errors(data)
    if errors:
        raise RuntimeError(f"Scenario contract failed for {name}: {errors}")
    spec_path = work / f"{name}-slide-spec.json"
    spec_report = work / f"{name}-slide-spec-report.json"
    spec_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    run_checked(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_slide_spec.py"),
            str(spec_path),
            "--output",
            str(spec_report),
            "--json",
        ],
        f"{name}: Slide Spec validation",
    )
    return spec_path, spec_report


def exercise_cross_workflow_contracts(
    work: Path,
    tool: Path,
    delivery: Path,
    pptx: Path,
    package_report: Path,
    spec_report: Path,
    notes: Path,
) -> list[str]:
    completed = ["outline-handoff", "create"]
    static_check = ROOT / "skills" / "sp-review" / "scripts" / "pptx_static_check.py"
    run_checked(
        [sys.executable, str(static_check), str(pptx), "--json"],
        "review-static-only",
    )
    completed.append("review-static-only")

    summary = work / "review-to-deck-summary.md"
    summary.write_text("# Production Summary\n\nReview findings will be applied to a new output.", encoding="utf-8")
    state = work / "review-to-deck-state.json"
    guard = ROOT / "scripts" / "workflow_guard.py"
    run_checked([sys.executable, str(guard), "init", "--state-file", str(state)], "review-to-deck: init")
    run_checked(
        [sys.executable, str(guard), "confirm", "--state-file", str(state), "--summary-file", str(summary)],
        "review-to-deck: confirm",
    )
    run_checked(
        [sys.executable, str(guard), "transition", "--state-file", str(state), "--to", "planned"],
        "review-to-deck: plan",
    )
    if json.loads(state.read_text(encoding="utf-8"))["state"] != "planned":
        raise RuntimeError("review-to-deck: Production Summary confirmation was not enforced")
    completed.append("review-to-deck")

    incomplete_report = work / "missing-render-delivery-report.json"
    run_checked(
        [
            sys.executable, str(delivery), "--simple", "--pptx", str(pptx),
            "--notes", str(notes), "--slide-spec-report", str(spec_report),
            "--package-report", str(package_report), "--allow-missing-preview",
            "--output", str(incomplete_report), "--json",
        ],
        "missing-render-incomplete: delivery",
    )
    if json.loads(incomplete_report.read_text(encoding="utf-8"))["status"] != "incomplete":
        raise RuntimeError("missing-render-incomplete: delivery did not remain incomplete")
    completed.append("missing-render-incomplete")

    source_hash = hashlib.sha256(pptx.read_bytes()).hexdigest()
    rebuilt = generate_deck(work, "rebuild-contract", "Chinese", ["problem", "method", "result"])
    run_checked(
        [sys.executable, str(tool), "validate", str(rebuilt), "--original", str(pptx), "--json"],
        "rebuild",
    )
    if rebuilt.resolve() == pptx.resolve() or hashlib.sha256(pptx.read_bytes()).hexdigest() != source_hash:
        raise RuntimeError("rebuild: source was overwritten or output was not independent")
    completed.append("rebuild")
    return completed


def write_visual_review(pptx: Path, path: Path, page_count: int) -> None:
    """Author a sha256-bound visual-review report for the rendered scenario.

    The simplified delivery gate rejects a bare ``--visual-reviewed`` flag:
    completion requires a report file bound to the current PPTX hash with
    per-slide entries (review item fatal 1). The matrix exercises exactly
    that contract by authoring the report after the pages are rendered.
    """
    digest = hashlib.sha256(pptx.read_bytes()).hexdigest()
    slides = [
        {
            "slide": number,
            "visual_structure": "reviewed",
            "scores": {
                "hierarchy": 8,
                "focal_point": 8,
                "composition": 8,
                "visual_interest": 8,
                "whitespace": 8,
            },
            "ai_template_feel": "none",
            "issues": [],
        }
        for number in range(1, page_count + 1)
    ]
    path.write_text(
        json.dumps(
            {"pptx_sha256": digest, "slides": slides, "deck": {"issues": []}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run temporary rendered PPTX scenario matrix")
    parser.add_argument("--require-render", action="store_true")
    args = parser.parse_args()
    if not find_soffice() or not find_pdftoppm():
        if args.require_render:
            raise SystemExit("LibreOffice soffice and pdftoppm are required for the render matrix.")
        print(json.dumps({"ok": True, "skipped": True, "reason": "LibreOffice or Poppler unavailable"}))
        return
    delivery = ROOT / "skills" / "sp-deck" / "scripts" / "pptx_delivery_check.py"
    tool = ROOT / "scripts" / "pptx_tool.py"
    completed = []
    workflow_scenarios: list[str] = exercise_adaptive_composition_contracts()
    with tempfile.TemporaryDirectory(prefix="sp-outline-matrix-") as tmp:
        work = Path(tmp)
        for name, (scenario, language, roles) in MATRIX.items():
            spec_path, spec_report = validate_scenario(
                work, name, scenario, language, roles
            )
            source = generate_deck(work, name, language, roles)
            original = None
            if name == "school-template-edit":
                pptx, source_hash = exercise_school_template_edit(work, tool, source)
                original = source
            else:
                pptx = source
                source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            notes = work / f"{name}-speaker-notes.md"
            notes.write_text("# Matrix notes\n", encoding="utf-8")
            package_report = work / f"{name}-package-report.json"
            validate_command = [
                sys.executable, str(tool), "validate", str(pptx),
                "--output", str(package_report), "--json",
            ]
            if original:
                validate_command.extend(["--original", str(original)])
            run_checked(
                validate_command,
                f"{name}: package validation",
            )
            render_dir = work / f"{name}-render"
            render_result = run_checked(
                [sys.executable, str(tool), "render", str(pptx), "--output-dir", str(render_dir), "--prefix", name],
                f"{name}: render",
            )
            render_payload = json.loads(render_result.stdout)
            if os.environ.get("PPTX_RUNTIME_FORCE_AF_UNIX_SHIM") == "1" and not any(
                "AF_UNIX denial simulation active" in message
                for message in render_payload.get("messages", [])
            ):
                raise RuntimeError(f"{name}: forced AF_UNIX shim was not activated")
            pages = sorted(render_dir.glob(f"{name}-*.png"))
            if len(pages) != len(roles):
                raise RuntimeError(f"{name}: rendered {len(pages)} pages for {len(roles)} slides")
            if not package_report.is_file():
                raise RuntimeError(f"{name}: package validation did not publish a report")
            delivery_command = [
                sys.executable,
                str(delivery),
                "--simple",
                "--visual-reviewed",
                "--visual-review-report",
                str(work / f"{name}-visual-review.json"),
                "--pptx",
                str(pptx),
                "--notes",
                str(notes),
                "--slide-spec-report",
                str(spec_report),
                "--package-report",
                str(package_report),
                "--strict",
                "--json",
            ]
            write_visual_review(pptx, work / f"{name}-visual-review.json", len(roles))
            for page in pages:
                delivery_command.extend(["--preview", str(page)])
            run_checked(delivery_command, f"{name}: strict delivery")
            if name == "coursework-zh":
                workflow_scenarios.extend(
                    exercise_cross_workflow_contracts(
                        work,
                        tool,
                        delivery,
                        pptx,
                        package_report,
                        spec_report,
                        notes,
                    )
                )
                exercise_rendered_review(work, tool, pptx, len(roles))
                workflow_scenarios.append("review-rendered")
            if hashlib.sha256(source.read_bytes()).hexdigest() != source_hash:
                raise RuntimeError(f"{name}: source hash changed during scenario")
            completed.append(name)
    print(
        json.dumps(
            {
                "ok": True,
                "rendered_scenarios": completed,
                "workflow_scenarios": workflow_scenarios,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
