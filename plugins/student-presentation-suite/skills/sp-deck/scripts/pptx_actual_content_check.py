#!/usr/bin/env python3
"""Compare actual PPTX text against Slide Spec after generation.

This deterministic readback guard reads slide XML directly and checks planned
slide count, titles, key claims, explicit slide_copy fragments and key numbers.
The report is bound to both the current PPTX and the current Slide Spec hashes.
"""

from __future__ import annotations

import argparse
import json
import posixpath
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.content_requirements import (  # noqa: E402
    exact_present,
    fact_binding_present,
    numbers,
    semantic_requirements,
)
from shared.hashing import file_sha256 as sha256_file  # noqa: E402

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"




def load_structured(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        value = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML is required for YAML Slide Spec files.") from exc
        value = yaml.safe_load(text)
    if not isinstance(value, dict):
        raise SystemExit("Slide Spec root must be an object.")
    return value


def normalize(text: str) -> str:
    text = re.sub(r"\s+", "", text or "")
    text = text.replace("“", '"').replace("”", '"').replace("’", "'")
    return text.casefold()


def extract_pptx_text(pptx: Path) -> list[str]:
    slides: list[tuple[int, str]] = []
    with zipfile.ZipFile(pptx) as zf:
        for name in zf.namelist():
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if not match:
                continue
            root = ET.fromstring(zf.read(name))
            from shared.pptx_text_readback import slide_text

            slides.append((int(match.group(1)), slide_text(root)))
    return [text for _, text in sorted(slides)]


def extract_fact_blocks(pptx: Path) -> list[list[str]]:
    from shared.pptx_text_readback import fact_blocks

    slides = []
    with zipfile.ZipFile(pptx) as package:
        for name in package.namelist():
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if match:
                slides.append((int(match.group(1)), fact_blocks(ET.fromstring(package.read(name)))))
    return [blocks for _, blocks in sorted(slides)]


NOTESLIDE_REL_RE = re.compile(r'Type="[^"]*?/notesSlide"[^>]*?Target="([^"]+)"')


def extract_pptx_notes(pptx: Path) -> dict[int, str]:
    """Per-slide speaker-notes text keyed by one-based slide number.

    The delivery contract is notes in the PPTX notes pane, so the timing gate
    must judge the artifact (2026-09-17: `speaker_notes_missing` fired 10x on a
    healthy deck because the frozen spec's `speaker_notes` field was never
    populated, while the PPTX notes pane was verified intact).
    """
    notes: dict[int, str] = {}
    with zipfile.ZipFile(pptx) as zf:
        names = set(zf.namelist())
        for name in names:
            match = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", name)
            if not match:
                continue
            slide_no = int(match.group(1))
            rels_name = f"ppt/slides/_rels/slide{slide_no}.xml.rels"
            if rels_name not in names:
                continue
            targets = NOTESLIDE_REL_RE.findall(zf.read(rels_name).decode("utf-8"))
            pieces: list[str] = []
            for target in targets:
                notes_path = posixpath.normpath(posixpath.join("ppt/slides", target))
                if notes_path not in names:
                    continue
                root = ET.fromstring(zf.read(notes_path))
                # Notes slides also contain a slide-number placeholder. Only the
                # body placeholder is the speaker's script.
                pieces = []
                for shape in root.iter(f"{{{P_NS}}}sp"):
                    placeholder = shape.find(
                        f"./{{{P_NS}}}nvSpPr/{{{P_NS}}}nvPr/{{{P_NS}}}ph"
                    )
                    if placeholder is not None and placeholder.get("type") == "body":
                        pieces.extend(node.text or "" for node in shape.iter(f"{{{A_NS}}}t"))
                break  # one notesSlide per slide
            notes[slide_no] = "\n".join(pieces).strip()
    return notes


def compact_fragments(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(compact_fragments(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for key in ("text", "title", "claim", "label", "value"):
            if key in value:
                result.extend(compact_fragments(value[key]))
        return result
    return []


def planned_slides(spec: dict[str, Any]) -> list[dict[str, Any]]:
    raw = spec.get("slides")
    if not isinstance(raw, list):
        raise SystemExit("Slide Spec must contain a slides list.")
    return [item for item in raw if isinstance(item, dict)]


NUMBER_RE = re.compile(r"(?<!\w)(?:\d+(?:\.\d+)?%?|\d{1,3}(?:,\d{3})+)(?!\w)")


def planned_requirements(planned: dict[str, Any]) -> dict[str, Any]:
    """Exactly what a slide must render, derived from the frozen spec.

    The readback gate and `page_brief.py` (what the builder reads instead of
    hand-rolling `node -e` extractors over the same files) both call this, so the
    requirement the builder is handed is byte-identical to the one that will be
    judged. Keep the number pattern in sync with `check()`, which is why it lives
    here rather than in either caller.
    """
    semantic = semantic_requirements(planned)
    if semantic is not None:
        exact = list(semantic.get("must_show_exact", []))
        numeric_facts = {number for requirement in semantic.get("must_convey", []) if requirement.get("placement", "slide") == "slide" for number in numbers(requirement["text"])}
        exact.extend(sorted(numeric_facts - set(exact)))
        return {
            "title": "", "claim": "", "copy_fragments": [],
            "numbers": sorted({n for text in exact for n in numbers(text)}),
            "must_show_exact": exact, "must_convey": semantic.get("must_convey", []),
            "fact_bindings": semantic.get("fact_bindings", []),
            "copy_policy": "semantic",
        }
    title = str(planned.get("title") or "").strip()
    claim = str(planned.get("claim") or planned.get("key_line") or "").strip()
    copy_fragments = compact_fragments(planned.get("slide_copy"))
    numeric_values = numbers(" ".join([title, claim, *copy_fragments]))
    return {
        "title": title,
        "claim": claim,
        "copy_fragments": copy_fragments,
        "numbers": numeric_values,
    }


def check(spec: dict[str, Any], actual: list[str], fact_blocks: list[list[str]] | None = None) -> dict[str, Any]:
    slides = planned_slides(spec)
    issues: list[dict[str, Any]] = []
    per_slide: list[dict[str, Any]] = []

    if len(slides) != len(actual):
        issues.append({
            "severity": "critical",
            "code": "slide_count_mismatch",
            "planned": len(slides),
            "actual": len(actual),
        })

    for index, planned in enumerate(slides, start=1):
        actual_text = actual[index - 1] if index <= len(actual) else ""
        actual_norm = normalize(actual_text)
        slide_issues: list[dict[str, Any]] = []

        requirements = planned_requirements(planned)
        facts = (semantic_requirements(planned) or {}).get("fact_bindings", [])
        blocks = fact_blocks[index - 1] if fact_blocks is not None and index <= len(fact_blocks) else actual_text.splitlines()
        for fact in facts:
            if not fact_binding_present(fact, blocks):
                slide_issues.append({"severity": "major", "code": "fact_binding_missing_or_changed", "fact": fact})
        for expected in requirements.get("must_show_exact", []):
            if not exact_present(expected, actual_text):
                slide_issues.append({"severity": "major", "code": "exact_content_missing", "expected": expected})
        title = requirements["title"]
        if title and normalize(title) not in actual_norm:
            slide_issues.append({"severity": "major", "code": "missing_title", "expected": title})

        claim = requirements["claim"]
        if claim and len(normalize(claim)) >= 6 and normalize(claim) not in actual_norm:
            slide_issues.append({"severity": "major", "code": "missing_key_claim", "expected": claim})

        copy_fragments = requirements["copy_fragments"]
        missing_copy = [frag for frag in copy_fragments if len(normalize(frag)) >= 6 and normalize(frag) not in actual_norm]
        if missing_copy:
            slide_issues.append({
                "severity": "minor" if len(missing_copy) == 1 else "major",
                "code": "planned_copy_missing",
                "missing": missing_copy[:8],
            })

        numeric_claims = requirements["numbers"]
        missing_numbers = sorted({n for n in numeric_claims if not exact_present(n, actual_text)})
        if missing_numbers:
            slide_issues.append({"severity": "major", "code": "planned_numbers_missing", "missing": missing_numbers})

        per_slide.append({
            "slide": index,
            "id": planned.get("id"),
            "title": title,
            "actual_text_chars": len(actual_text),
            "issues": slide_issues,
        })
        issues.extend({"slide": index, **issue} for issue in slide_issues)

    blockers = [i for i in issues if i.get("severity") in {"critical", "major"}]
    return {
        "ok": not blockers,
        "planned_slide_count": len(slides),
        "actual_slide_count": len(actual),
        "blocker_count": len(blockers),
        "issue_count": len(issues),
        "issues": issues,
        "slides": per_slide,
        "fact_binding_count": sum(len((semantic_requirements(slide) or {}).get("fact_bindings", [])) for slide in slides),
        "semantic_scope": "Exact tokens and opted-in metric/value/unit bindings only; unbound numbers, meaning, causality and claims require author review.",
    }


def run(args: argparse.Namespace) -> int:
    """Run the readback gate with pre-parsed arguments (shared by gate-all)."""
    if not args.pptx.is_file():
        raise SystemExit(f"PPTX does not exist: {args.pptx}")
    if not args.slide_spec.is_file():
        raise SystemExit(f"Slide Spec does not exist: {args.slide_spec}")

    spec = load_structured(args.slide_spec)
    actual = extract_pptx_text(args.pptx)
    has_bindings = any((semantic_requirements(slide) or {}).get("fact_bindings") for slide in planned_slides(spec))
    report = check(spec, actual, extract_fact_blocks(args.pptx) if has_bindings else None)
    if spec.get("schema_version") == "2.1":
        copy_path = args.pptx.parent / "presentation-copy.json"
        if not copy_path.is_file():
            copy_path = Path(str(args.pptx) + ".presentation-copy.json")
        try:
            copy = json.loads(copy_path.read_text(encoding="utf-8")) if copy_path.is_file() else {}
        except (OSError, ValueError):
            copy = {}
        if not isinstance(copy, dict):
            copy = {}
        if copy.get("pptx_sha256") != sha256_file(args.pptx) or not isinstance(copy.get("slides"), list) or len(copy["slides"]) != len(spec["slides"]):
            report["issues"].append({"severity": "major", "code": "presentation_copy_missing_or_stale"})
            report["blocker_count"] += 1
            report["issue_count"] += 1
            report["ok"] = False
        else:
            actual_notes = extract_pptx_notes(args.pptx)
            for index, entry in enumerate(copy["slides"], 1):
                if not isinstance(entry, dict):
                    entry = {}
                notes_copy = str(entry.get("speaker_notes") or "")
                metadata_valid = (
                    entry.get("slide") == index
                    and isinstance(entry.get("headline"), str)
                    and bool(entry["headline"].strip())
                    and isinstance(entry.get("visual_labels"), list)
                )
                text_valid = index <= len(actual) and all(exact_present(text, actual[index - 1]) for text in compact_fragments(entry.get("headline")) + compact_fragments(entry.get("visual_labels")))
                notes_valid = isinstance(entry.get("speaker_notes"), str) and normalize(notes_copy) == normalize(actual_notes.get(index, ""))
                runs = entry.get("text_runs")
                runs_valid = isinstance(runs, list) and all(isinstance(text, str) for text in runs) and index <= len(actual) and normalize("".join(runs)) == normalize(actual[index - 1])
                if not (metadata_valid and text_valid and notes_valid and runs_valid):
                    report["issues"].append({"slide": index, "severity": "major", "code": "presentation_copy_unbound"})
                    report["blocker_count"] += 1
                    report["issue_count"] += 1
                    report["ok"] = False
    report.update({
        "pptx": str(args.pptx.resolve()),
        "pptx_sha256": sha256_file(args.pptx),
        "slide_spec": str(args.slide_spec.resolve()),
        "slide_spec_sha256": sha256_file(args.slide_spec),
        "slide_count": report["actual_slide_count"],
    })
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    if args.json or not args.output:
        print(payload)
    if args.strict and not report["ok"]:
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx", type=Path)
    parser.add_argument("slide_spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
