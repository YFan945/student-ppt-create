#!/usr/bin/env python3
"""Compare actual PPTX text against Slide Spec after generation.

This deterministic readback guard reads slide XML directly and checks planned
slide count, titles, key claims, explicit slide_copy fragments and key numbers.
The report is bound to both the current PPTX and the current Slide Spec hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
            pieces = [node.text or "" for node in root.iter(f"{{{A_NS}}}t")]
            slides.append((int(match.group(1)), "\n".join(pieces)))
    return [text for _, text in sorted(slides)]


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


def check(spec: dict[str, Any], actual: list[str]) -> dict[str, Any]:
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

        title = str(planned.get("title") or "").strip()
        if title and normalize(title) not in actual_norm:
            slide_issues.append({"severity": "major", "code": "missing_title", "expected": title})

        claim = str(planned.get("claim") or planned.get("key_line") or "").strip()
        if claim and len(normalize(claim)) >= 6 and normalize(claim) not in actual_norm:
            slide_issues.append({"severity": "major", "code": "missing_key_claim", "expected": claim})

        copy_fragments = compact_fragments(planned.get("slide_copy"))
        missing_copy = [frag for frag in copy_fragments if len(normalize(frag)) >= 6 and normalize(frag) not in actual_norm]
        if missing_copy:
            slide_issues.append({
                "severity": "minor" if len(missing_copy) == 1 else "major",
                "code": "planned_copy_missing",
                "missing": missing_copy[:8],
            })

        numeric_claims = re.findall(
            r"(?<!\w)(?:\d+(?:\.\d+)?%?|\d{1,3}(?:,\d{3})+)(?!\w)",
            " ".join([title, claim, *copy_fragments]),
        )
        missing_numbers = sorted({n for n in numeric_claims if normalize(n) not in actual_norm})
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
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pptx", type=Path)
    parser.add_argument("slide_spec", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not args.pptx.is_file():
        raise SystemExit(f"PPTX does not exist: {args.pptx}")
    if not args.slide_spec.is_file():
        raise SystemExit(f"Slide Spec does not exist: {args.slide_spec}")

    spec = load_structured(args.slide_spec)
    report = check(spec, extract_pptx_text(args.pptx))
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


if __name__ == "__main__":
    sys.exit(main())
