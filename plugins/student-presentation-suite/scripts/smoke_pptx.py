#!/usr/bin/env python3
"""Generate and validate a minimal PPTX through the runtime wrapper."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate and validate a temporary PPTX through the suite runtime"
    )
    parser.add_argument("--json", action="store_true", help="Emit compact JSON")
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="Stop after generation and package validation (for runners without LibreOffice/Poppler)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="sp-outline-smoke-") as tmp:
        work = Path(tmp)
        pptx = work / "smoke-presentation.pptx"
        notes = work / "smoke-speaker-notes.md"
        deck_script = work / "deck.js"
        deck_script.write_text(
            """\
const pptxgen = require("pptxgenjs");
const H = require("pptx-helpers");

const TOKENS = {
  palette: { canvas: "FFFFFF", surface: "FFFFFF", primary_text: "111827",
             secondary_text: "4B5563", primary_accent: "2563EB", secondary_accent: "93C5FD" },
  typography: { title_min_pt: 24, body_cjk_min_pt: 22, body_latin_min_pt: 20,
                title_font: "Cambria", body_font: "Calibri" },
  geometry: { safe_margin_pct: 6, title_zone_pct: 16, footer_zone_pct: 5,
              spacing_scale_pt: [6,12,18,24,36,48], corner_radius_pt: 8 },
  lines: { standard_pt: 1.25, emphasis_pt: 2.5 }
};
const LANG = "english";

const pptx = new pptxgen();
H.applyTokens(pptx, TOKENS, LANG);

const AREA = H.safeArea(H.SLIDE_W_IN, H.SLIDE_H_IN, TOKENS);
const slide = pptx.addSlide();
slide.background = { fill: H.color(TOKENS, "canvas") };
H.addTitle(slide, "Claude Code PPTX smoke test", AREA, TOKENS, LANG);
H.addTextBox(slide, "Runtime resolution and delivery validation", {
  x: AREA.x, y: AREA.y + AREA.h * 0.25, w: AREA.w, h: AREA.h * 0.4
}, TOKENS, LANG, { color: H.color(TOKENS, "secondary_text") });

slide.addNotes("Smoke test notes.");
pptx.writeFile({ fileName: process.argv[2] });
""",
            encoding="utf-8",
        )
        subprocess.run(
            [
                "node",
                str(ROOT / "scripts/run_with_pptxgenjs.js"),
                "--output",
                str(pptx),
                str(deck_script),
            ],
            check=True,
        )
        # Exercise the current user route once, without manufacturing visual receipts.
        spec = work / "slide-spec.json"
        selected = ["pptx"] if args.skip_render else ["pptx", "speaker-notes", "preview"]
        spec.write_text(json.dumps({
            "schema_version": "2.1", "research_scope": "C",
            "meta": {"topic": "Runtime smoke", "slide_count": 1, "duration_min": 1,
                     "include_speaker_notes": True, "deliverables": selected},
            "slides": [{"id": 1, "title": "Claude Code PPTX smoke test",
                        "content": ["Runtime resolution and delivery validation"],
                        "semantic_requirements": {"must_convey": [{"id": "runtime", "text": "Runtime integration"}],
                                                  "must_show_exact": ["Runtime resolution and delivery validation"]}}]
        }), encoding="utf-8")
        command = [sys.executable, str(ROOT / "skills/sp-deck/scripts/delivery_check.py"),
                   "--pptx", str(pptx), "--slide-spec", str(spec), "--json",
                   "--output", str(work / "delivery-report.json")]
        if not args.skip_render:
            notes.write_text("# Speaker notes\n\nSmoke test notes.", encoding="utf-8")
            render_dir = work / "render"
            rendered = subprocess.run(
                [sys.executable, str(ROOT / "scripts/pptx_tool.py"), "render", str(pptx),
                 "--output-dir", str(render_dir), "--prefix", "smoke"],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if rendered.returncode:
                raise SystemExit(rendered.stdout + rendered.stderr)
            command.extend(["--notes", str(notes), "--preview", str(render_dir / "smoke-1.png")])
        checked = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if checked.returncode:
            raise SystemExit(checked.stdout + checked.stderr)
        result = json.loads(checked.stdout)
        if not result["ok"] or result.get("content", {}).get("actual_slide_count") != 1:
            raise SystemExit(f"Unexpected smoke result: {result}")
        print(json.dumps({"ok": True, "slide_count": 1, "stage": "package-validation" if args.skip_render else "rendered-delivery",
                          "render_skipped": args.skip_render, "visual_quality_verified": False}, indent=None if args.json else 2))


if __name__ == "__main__":
    main()
