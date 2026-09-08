#!/usr/bin/env python3
"""Compare the actual PPTX artifact with Slide Spec.

The goal is not pixel equivalence. It catches semantic drift introduced between
planning and rendering: wrong slide count, missing/changed titles, and planned
numbers disappearing from the actual slide.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import yaml

NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or "").lower(), flags=re.UNICODE)


def similarity(a: str, b: str) -> float:
    aa, bb = normalize(a), normalize(b)
    if not aa or not bb:
        return 0.0
    if aa in bb or bb in aa:
        return 1.0
    return SequenceMatcher(None, aa, bb).ratio()


def numbers(value: Any) -> set[str]:
    if isinstance(value, dict):
        text = " ".join(str(v) for v in value.values())
    elif isinstance(value, list):
        text = " ".join(str(v) for v in value)
    else:
        text = str(value or "")
    # Include percentages and ordinary numeric claims while ignoring single slide ids.
    return set(re.findall(r"(?<!\w)(?:\d+(?:\.\d+)?%|\d{2,}(?:\.\d+)?)(?!\w)", text))


def read_spec(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Slide Spec root must be a mapping")
    return data


def read_actual_slides(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        names = sorted(
            [n for n in archive.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")],
            key=lambda n: int(Path(n).stem.replace("slide", "")),
        )
        result: list[str] = []
        for name in names:
            root = ET.fromstring(archive.read(name))
            texts = [node.text or "" for node in root.findall(".//a:t", NS)]
            result.append("\n".join(t for t in texts if t.strip()))
        return result


def planned_text(slide: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("title", "claim", "key_line", "slide_copy", "content", "supporting_points"):
        value = slide.get(key)
        if isinstance(value, dict):
            parts.extend(str(v) for v in value.values())
        elif isinstance(value, list):
            parts.extend(str(v) for v in value)
        elif value is not None:
            parts.append(str(value))
    return "\n".join(parts)


def analyze(spec_path: Path, pptx_path: Path) -> dict[str, Any]:
    spec = read_spec(spec_path)
    planned = spec.get("slides") or []
    if not isinstance(planned, list):
        raise ValueError("Slide Spec slides must be a list")
    actual = read_actual_slides(pptx_path)
    findings: list[dict[str, Any]] = []

    if len(planned) != len(actual):
        findings.append(
            {
                "severity": "blocker",
                "code": "slide_count_drift",
                "slide": None,
                "message": f"计划 {len(planned)} 页，实际 PPTX 为 {len(actual)} 页。",
            }
        )

    for idx, slide in enumerate(planned[: len(actual)], start=1):
        if not isinstance(slide, dict):
            continue
        actual_text = actual[idx - 1]
        title = str(slide.get("title") or "").strip()
        if title and similarity(title, actual_text) < 0.72:
            findings.append(
                {
                    "severity": "major",
                    "code": "title_drift",
                    "slide": idx,
                    "message": "实际页面未保留计划标题或标题发生明显漂移。",
                    "planned": title,
                    "actual_preview": actual_text[:180],
                }
            )

        p_text = planned_text(slide)
        for token in sorted(numbers(p_text)):
            if token not in actual_text:
                findings.append(
                    {
                        "severity": "major",
                        "code": "planned_number_missing",
                        "slide": idx,
                        "message": f"计划中的关键数字 {token} 未出现在实际页面。",
                        "planned_number": token,
                    }
                )

        claim = str(slide.get("claim") or "").strip()
        if claim and len(normalize(claim)) >= 8 and similarity(claim, actual_text) < 0.48:
            findings.append(
                {
                    "severity": "warning",
                    "code": "claim_drift_risk",
                    "slide": idx,
                    "message": "实际页面与计划 claim 相似度偏低，请在视觉复审时确认信息结论是否仍然成立。",
                    "planned": claim,
                }
            )

    blockers = sum(1 for f in findings if f["severity"] == "blocker")
    majors = sum(1 for f in findings if f["severity"] == "major")
    warnings = sum(1 for f in findings if f["severity"] == "warning")
    return {
        "ok": blockers == 0 and majors == 0,
        "profile": "plan-vs-actual-v1",
        "slide_spec": str(spec_path.resolve()),
        "pptx": str(pptx_path.resolve()),
        "pptx_sha256": sha256_file(pptx_path),
        "planned_slide_count": len(planned),
        "actual_slide_count": len(actual),
        "blockers": blockers,
        "majors": majors,
        "warnings": warnings,
        "findings": findings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Slide Spec with actual PPTX text.")
    parser.add_argument("slide_spec", type=Path)
    parser.add_argument("pptx", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()

    if not args.slide_spec.is_file():
        parser.error(f"Slide Spec not found: {args.slide_spec}")
    if not args.pptx.is_file():
        parser.error(f"PPTX not found: {args.pptx}")
    try:
        report = analyze(args.slide_spec, args.pptx)
    except Exception as exc:  # deterministic CLI should surface a structured failure
        report = {"ok": False, "error": str(exc)}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if args.json or not args.output:
        print(text, end="")
    if args.strict and report.get("ok") is not True:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
