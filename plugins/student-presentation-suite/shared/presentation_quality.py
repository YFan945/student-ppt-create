"""Deterministic quality checks for Student Presentation Slide Spec data."""

from __future__ import annotations

import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from shared.quality_tiers import normalize as normalize_tier
from shared.slide_spec_validation import _validate_scenario_roles

GENERIC_PATTERNS = (
    "在当今社会快速发展的背景下",
    "具有十分重要的意义",
    "我们应该高度重视",
    "it is very important",
    "in today's rapidly developing society",
    "completely solves",
    "comprehensively improves",
)
CAUSAL_MARKERS = ("导致", "造成", "因此", "because", "causes", "leads to")
NUMBER_RE = re.compile(r"(?<![A-Za-z])(?:\d+(?:\.\d+)?%?|\d{2,}(?:,\d{3})*)")
ROLE_ORDER = {
    "opening": 0,
    "background": 1,
    "problem": 2,
    "method": 3,
    "solution": 3,
    "evidence": 4,
    "result": 5,
    "value": 6,
    "limitation": 7,
    "conclusion": 8,
    "qa": 9,
    "closing": 10,
}


def text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return " ".join(text_value(item) for item in value)
    if isinstance(value, dict):
        return " ".join(text_value(item) for item in value.values())
    return ""


def normalized(value: Any) -> str:
    return re.sub(r"\W+", "", text_value(value).lower())


def finding(
    severity: str,
    target: str,
    code: str,
    problem: str,
    impact: str,
    fix: str,
) -> dict[str, str]:
    return {
        "severity": severity,
        "target": target,
        "code": code,
        "problem": problem,
        "impact": impact,
        "fix": fix,
    }


def slide_score(slide_findings: list[dict[str, str]]) -> dict[str, int]:
    penalties = Counter()
    for item in slide_findings:
        weight = {"Critical": 30, "Major": 15, "Minor": 6}.get(item["severity"], 5)
        code = item["code"]
        if "evidence" in code or "source" in code:
            penalties["evidence"] += weight
        elif "transition" in code or "notes" in code or "timing" in code:
            penalties["speakability"] += weight
        elif "density" in code or "copy" in code:
            penalties["readability"] += weight
        elif "question" in code or "limitation" in code:
            penalties["defense_readiness"] += weight
        else:
            penalties["logic"] += weight
    return {
        "logic": max(0, 100 - penalties["logic"]),
        "evidence": max(0, 100 - penalties["evidence"]),
        "readability": max(0, 100 - penalties["readability"]),
        "speakability": max(0, 100 - penalties["speakability"]),
        "defense_readiness": max(0, 100 - penalties["defense_readiness"]),
    }


def analyze_spec(data: dict[str, Any]) -> dict[str, Any]:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    slides = data.get("slides") if isinstance(data.get("slides"), list) else []
    evidence = data.get("evidence_ledger") if isinstance(data.get("evidence_ledger"), list) else []
    evidence_ids = {item.get("id") for item in evidence if isinstance(item, dict)}
    findings: list[dict[str, str]] = []
    slide_findings: dict[int, list[dict[str, str]]] = {}

    raw_words = meta.get("max_words_per_slide")
    max_words = int(raw_words) if raw_words is not None else 40
    raw_chars = meta.get("max_chinese_chars_per_slide")
    max_chars = int(raw_chars) if raw_chars is not None else 80
    include_notes = bool(meta.get("include_speaker_notes", True))

    # 场景故事角色完整性检查（仅提示，不阻断：避免逼页数膨胀/凑角色）
    role_errors = _validate_scenario_roles(meta, slides)
    for err in role_errors:
        findings.append(
            finding(
                "Minor",
                err["path"],
                "missing-story-role",
                err["message"],
                "Audience may miss required narrative structure for this scenario type.",
                "Ensure every required story role group is represented across slides.",
            )
        )

    previous_roles: list[tuple[int, str]] = []
    seen_texts: list[tuple[int, str]] = []
    for index, slide in enumerate(slides):
        if not isinstance(slide, dict):
            continue
        slide_id = int(slide.get("id") or index + 1)
        target = f"Slide {slide_id}"
        current: list[dict[str, str]] = []
        kind = slide.get("kind", "content")
        role = slide.get("role")
        title = str(slide.get("title", ""))
        copy_text = text_value(slide.get("slide_copy", slide.get("content", ""))).strip()
        all_text = " ".join(
            part
            for part in (
                title,
                str(slide.get("claim", "")),
                copy_text,
                text_value(slide.get("supporting_points", [])),
            )
            if part
        )

        if kind == "content" and not slide.get("claim"):
            current.append(
                finding(
                    "Major",
                    target,
                    "missing-claim",
                    "Content slide has no explicit claim.",
                    "The page can degrade into a list of facts without a message.",
                    "Add one concise claim and make the title express it.",
                )
            )
        if len(re.findall(r"[\u4e00-\u9fff]", copy_text)) > max_chars:
            current.append(
                finding(
                    "Major",
                    target,
                    "chinese-density",
                    f"Chinese slide copy exceeds the confirmed {max_chars}-character limit.",
                    "Projection readability and speaking space are reduced.",
                    "Keep the claim and evidence on slide; move explanation to notes.",
                )
            )
        if len(re.findall(r"\b[\w'-]+\b", copy_text)) > max_words:
            current.append(
                finding(
                    "Major",
                    target,
                    "word-density",
                    f"Slide copy exceeds the confirmed {max_words}-word limit.",
                    "The audience is likely to read instead of listen.",
                    "Compress the slide copy and move detail to speaker notes.",
                )
            )
        if include_notes and kind == "content" and not slide.get("speaker_notes") and not slide.get("note_goal"):
            current.append(
                finding(
                    "Minor",
                    target,
                    "missing-notes",
                    "No speaker notes or note goal is supplied.",
                    "Timing and explainability cannot be checked reliably.",
                    "Add natural speaker notes with evidence context and one transition.",
                )
            )
        if index < len(slides) - 1 and kind == "content" and not slide.get("transition"):
            current.append(
                finding(
                    "Minor",
                    target,
                    "missing-transition",
                    "The slide has no transition to the next page.",
                    "The deck may feel like disconnected pages.",
                    "Add a sentence that states the logical relationship to the next slide.",
                )
            )
        refs = slide.get("evidence_refs") or []
        unknown_refs = [ref for ref in refs if ref not in evidence_ids]
        if unknown_refs:
            current.append(
                finding(
                    "Critical",
                    target,
                    "unknown-evidence-reference",
                    f"Evidence references are missing from the ledger: {', '.join(unknown_refs)}.",
                    "The claim cannot be traced to a source.",
                    "Add the ledger entries or remove the unsupported references.",
                )
            )
        factual_signal = bool(NUMBER_RE.search(all_text) or any(marker in all_text.lower() for marker in CAUSAL_MARKERS))
        if factual_signal and not refs:
            current.append(
                finding(
                    "Minor",
                    target,
                    "missing-evidence-reference",
                    "A numeric or causal claim has no evidence reference.",
                    "Teachers or judges may challenge the source or causal basis.",
                    "Link the claim to the Evidence Ledger or mark it as an assumption.",
                )
            )
        generic_matches = [pattern for pattern in GENERIC_PATTERNS if pattern.lower() in all_text.lower()]
        if generic_matches:
            current.append(
                finding(
                    "Major",
                    target,
                    "generic-ai-wording",
                    f"Generic or inflated wording detected: {generic_matches[0]}",
                    "The language sounds templated and weakens credibility.",
                    "Replace it with a concrete course, project, method, result, or limitation.",
                )
            )
        norm = normalized((title, slide.get("claim"), copy_text))
        if norm:
            for earlier_id, earlier_norm in seen_texts:
                if min(len(norm), len(earlier_norm)) >= 12 and SequenceMatcher(None, norm, earlier_norm).ratio() >= 0.86:
                    current.append(
                        finding(
                            "Major",
                            target,
                            "duplicate-slide",
                            f"Content substantially repeats Slide {earlier_id}.",
                            "Repeated pages consume time without advancing the argument.",
                            "Merge the pages or give this slide a distinct claim and evidence role.",
                        )
                    )
                    break
            seen_texts.append((slide_id, norm))
        if role in ROLE_ORDER:
            previous_roles.append((slide_id, role))

        findings.extend(current)
        slide_findings[slide_id] = current

    ordered_values = [ROLE_ORDER[role] for _, role in previous_roles]
    for idx in range(1, len(ordered_values)):
        if ordered_values[idx] + 1 < ordered_values[idx - 1]:
            slide_id, role = previous_roles[idx]
            findings.append(
                finding(
                    "Major",
                    f"Slide {slide_id}",
                    "role-order-regression",
                    f"Story role {role!r} appears after a later-stage role.",
                    "The argument can jump backward or reveal conclusions before support.",
                    "Reorder the page or explain the deliberate preview/recap structure.",
                )
            )

    roles = {role for _, role in previous_roles}
    if slides and not roles.intersection({"opening", "problem"}):
        findings.append(
            finding(
                "Minor",
                "Deck",
                "missing-opening-hook",
                "No opening/problem role is declared.",
                "The deck lacks a deterministic hook and framing check.",
                "Open with a concrete question, conflict, scene, data point, or concise conclusion.",
            )
        )
    if slides and not roles.intersection({"conclusion", "closing"}):
        findings.append(
            finding(
                "Minor",
                "Deck",
                "missing-closing",
                "No conclusion or closing role is declared.",
                "The presentation may end without a memorable takeaway or Q&A cue.",
                "Add a conclusion/closing page with takeaway, limitation/next step, and Q&A cue.",
            )
        )
    if normalize_tier(meta.get("quality_level")) == "rigorous" and not roles.intersection({"limitation"}):
        findings.append(
            finding(
                "Minor",
                "Deck",
                "missing-limitation",
                "Rigorous (high-score) mode has no limitation page or role.",
                "The conclusion can appear overstated and invite difficult questions.",
                "Add a limitation, boundary, or next-step section.",
            )
        )

    used_refs = {
        ref
        for slide in slides
        if isinstance(slide, dict)
        for ref in (slide.get("evidence_refs") or [])
    }
    for evidence_id in sorted(evidence_ids - used_refs):
        findings.append(
            finding(
                "Minor",
                "Evidence Ledger",
                "unused-evidence",
                f"Evidence {evidence_id!r} is not referenced by any slide.",
                "The ledger and deck can drift apart.",
                "Use it on a slide or remove it from the active ledger.",
            )
        )

    per_slide = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = int(slide.get("id") or len(per_slide) + 1)
        scores = slide_score(slide_findings.get(slide_id, []))
        per_slide.append(
            {
                "slide": slide_id,
                "scores": scores,
                "overall": round(sum(scores.values()) / len(scores)),
                "finding_count": len(slide_findings.get(slide_id, [])),
            }
        )
    counts = Counter(item["severity"] for item in findings)
    return {
        "ok": counts["Critical"] == 0 and counts["Major"] == 0,
        "summary": {
            "slide_count": len(slides),
            "critical": counts["Critical"],
            "major": counts["Major"],
            "minor": counts["Minor"],
        },
        "per_slide": per_slide,
        "findings": findings,
    }


