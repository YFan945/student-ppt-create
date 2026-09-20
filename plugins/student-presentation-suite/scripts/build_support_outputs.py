#!/usr/bin/env python3
"""Build confirmed support outputs from a validated Slide Spec."""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.slide_spec_contract import validate_slide_spec

SUPPORTED = {
    "speaker-notes",
    "full-script",
    "teleprompter",
    "training-cards",
    "references",
}


def load_optional_dependencies():
    try:
        import jsonschema  # noqa: F401
        import yaml  # noqa: F401
    except ImportError as exc:
        print(
            "Missing dependency. Install Slide Spec dependencies with: "
            "python -m pip install -r requirements.txt",
            file=sys.stderr,
        )
        raise SystemExit(3) from exc


def load_spec(path: Path) -> dict[str, Any]:
    import yaml
    raw = path.read_text(encoding="utf-8")
    value = json.loads(raw) if path.suffix.lower() == ".json" else yaml.safe_load(raw)
    if not isinstance(value, dict):
        raise ValueError("Slide Spec must be an object")
    return value


def teleprompter_html(data: dict[str, Any]) -> str:
    topic = html.escape(str((data.get("meta") or {}).get("topic") or "Presentation"))
    sections = []
    for slide in data.get("slides", []):
        if not isinstance(slide, dict):
            continue
        try:
            slide_id = int(slide.get("id") or 0)
        except (ValueError, TypeError):
            slide_id = 0
        title = html.escape(str(slide.get("title") or f"Slide {slide_id}"))
        notes = html.escape(str(slide.get("speaker_notes") or slide.get("note_goal") or ""))
        transition = html.escape(str(slide.get("transition") or ""))
        key_line = html.escape(str(slide.get("key_line") or ""))
        try:
            timing = int(slide.get("timing_sec") or 0)
        except (ValueError, TypeError):
            timing = 0
        sections.append(
            f"""<section data-slide="{slide_id}">
<div class="meta">Slide {slide_id} · {timing}s</div>
<h2>{title}</h2>
{f'<p class="key">{key_line}</p>' if key_line else ''}
<p>{notes}</p>
{f'<p class="transition">Next: {transition}</p>' if transition else ''}
</section>"""
        )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{topic} Teleprompter</title>
<style>
body{{margin:0;background:#111;color:#f5f5f5;font:28px/1.55 system-ui,sans-serif}}
main{{max-width:980px;margin:auto;padding:6vh 6vw 30vh}}
section{{min-height:76vh;padding:5vh 0;border-bottom:1px solid #444}}
h1{{font-size:1.5em}}h2{{font-size:1.35em;color:#8dd7ff}}
.meta{{font-size:.65em;color:#aaa}}.key{{font-weight:700;color:#ffd166}}
.transition{{color:#9ee493;font-style:italic}}
</style></head><body><main><h1>{topic}</h1>{''.join(sections)}</main></body></html>
"""


def training_cards(data: dict[str, Any]) -> str:
    lines = ["# Presentation Training Cards", ""]
    for slide in data.get("slides", []):
        if not isinstance(slide, dict):
            continue
        slide_id = slide.get("id")
        points = slide.get("supporting_points") or []
        keywords = [str(item) for item in points[:5]]
        if slide.get("claim"):
            keywords.insert(0, str(slide["claim"]))
        lines.extend(
            [
                f"## Slide {slide_id}: {slide.get('title', '')}",
                f"- Speaking goal: {slide.get('note_goal') or slide.get('claim') or 'Explain the page clearly'}",
                f"- Keywords: {', '.join(keywords[:5]) or 'Add 3-5 cues'}",
                f"- Planned seconds: {slide.get('timing_sec', 'not specified')}",
                "- Likely question: What evidence, method, or limitation supports this page?",
                f"- Answer points: {slide.get('speaker_notes') or 'Use the evidence and limitation from the Slide Spec.'}",
                "- Avoid overstating: Do not claim more than the referenced evidence supports.",
                "",
            ]
        )
    return "\n".join(lines)


def references_markdown(data: dict[str, Any]) -> str:
    style = (data.get("meta") or {}).get("citation_style") or "classroom"
    lines = [f"# References ({style})", ""]
    for item in data.get("evidence_ledger", []):
        if not isinstance(item, dict):
            continue
        author = item.get("author") or "Unknown author"
        date = item.get("date") or "n.d."
        title = item.get("title") or item.get("id")
        locator = item.get("locator") or ""
        confidence = item.get("confidence") or "unverified"
        lines.append(f"- [{item.get('id')}] {author}. ({date}). {title}. {locator} Confidence: {confidence}.")
    if len(lines) == 2:
        lines.append("- No evidence entries supplied.")
    return "\n".join(lines) + "\n"


def speaker_notes_markdown(data: dict[str, Any]) -> str:
    lines = ["# Speaker Notes", ""]
    for slide in data.get("slides", []):
        if not isinstance(slide, dict):
            continue
        lines.extend(
            [
                f"## Slide {slide.get('id')}: {slide.get('title', '')}",
                str(slide.get("speaker_notes") or slide.get("note_goal") or ""),
                "",
            ]
        )
    return "\n".join(lines)


def full_script_markdown(data: dict[str, Any]) -> str:
    lines = ["# Full Presentation Script", ""]
    for slide in data.get("slides", []):
        if not isinstance(slide, dict):
            continue
        script = slide.get("speaker_notes") or slide.get("note_goal") or slide.get("claim") or ""
        lines.extend([f"## Slide {slide.get('id')}: {slide.get('title', '')}", str(script)])
        if slide.get("transition"):
            lines.append(f"Transition: {slide['transition']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    load_optional_dependencies()
    parser = argparse.ArgumentParser(description="Build support outputs from Slide Spec")
    parser.add_argument("spec", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--prefix")
    parser.add_argument(
        "--only",
        action="append",
        choices=sorted(SUPPORTED),
        help="Generate only this support output; repeat for multiple outputs",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        data, errors, _ = validate_slide_spec(
            args.spec, ROOT / "references" / "slide-spec.schema.json"
        )
        if errors:
            raise ValueError(
                "Slide Spec validation failed: "
                + "; ".join(f"{error['path']}: {error['message']}" for error in errors)
            )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2) from exc
    prefix = args.prefix or (data.get("meta") or {}).get("output_prefix") or args.spec.stem
    args.output_dir.mkdir(parents=True, exist_ok=True)
    spec_meta = data.get("meta") or {}
    confirmed = set(spec_meta.get("deliverables") or spec_meta.get("export_formats") or [])
    requested = set(args.only or [])
    unconfirmed = requested - confirmed
    if unconfirmed:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "--only requested unconfirmed deliverables: "
                    + ", ".join(sorted(unconfirmed)),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(2)
    selected = requested if requested else confirmed & SUPPORTED
    renderers = {
        "speaker-notes": (f"{prefix}-speaker-notes.md", speaker_notes_markdown),
        "full-script": (f"{prefix}-full-script.md", full_script_markdown),
        "teleprompter": (f"{prefix}-teleprompter.html", teleprompter_html),
        "training-cards": (f"{prefix}-training-cards.md", training_cards),
        "references": (f"{prefix}-references.md", references_markdown),
    }
    outputs = {
        name: args.output_dir / renderers[name][0]
        for name in sorted(selected)
    }
    try:
        for name, path in outputs.items():
            path.write_text(renderers[name][1](data), encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(1) from exc
    result = {"ok": True, "outputs": {name: str(path.resolve()) for name, path in outputs.items()}}
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "\n".join(result["outputs"].values()))


if __name__ == "__main__":
    main()
