"""Frozen information requirements shared by source checks, readback and critic."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

# ASCII token boundaries intentionally allow adjoining Chinese characters.
NUMBER_RE = re.compile(r"(?<![\d.+-])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?(?!\d|\.\d|,\d|[%％])")


def notes_digest(notes: dict[int, str]) -> str:
    return hashlib.sha256(json.dumps(notes, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def semantic_binding(spec_sha256: str, actual: list[str], notes: dict[int, str]) -> dict[str, str]:
    return {"slide_spec_sha256": spec_sha256, "notes_sha256": notes_digest(notes), "text_sha256": hashlib.sha256(json.dumps(actual, ensure_ascii=False).encode("utf-8")).hexdigest()}


def numbers(text: str) -> list[str]:
    return sorted(set(NUMBER_RE.findall(text)))


def exact_present(expected: str, actual: str) -> bool:
    """No substring match for numbers; wrapping whitespace does not change copy."""
    compact = re.sub(r"\s+", "", expected)
    if re.fullmatch(r"[+-]?\d[\d,.]*[%％]?", compact):
        return compact in numbers(actual)
    parts: list[str] = []
    offset = 0
    for token in NUMBER_RE.finditer(compact):
        parts.extend(re.escape(char) for char in compact[offset:token.start()])
        parts.append(r"(?<![\d.+-])(?<!\d,)" + re.escape(token.group()) + r"(?!\d|\.\d|,\d|[%％])")
        offset = token.end()
    parts.extend(re.escape(char) for char in compact[offset:])
    # Whitespace may separate displayed words/lines, never digits in a token.
    # Bind numeric boundaries to this quotation, not some other number on the page.
    return bool(re.search(r"\s*".join(parts), actual))


def semantic_requirements(slide: dict[str, Any]) -> dict[str, Any] | None:
    value = slide.get("semantic_requirements")
    return value if isinstance(value, dict) else None


def fact_binding_present(fact: dict[str, str], blocks: list[str]) -> bool:
    """Match an opted-in metric/value/unit in one actual OOXML text block.

    Label before or after value is supported, including wrapping/colon. No
    inferred synonyms, arithmetic, or union of unrelated text boxes is used.
    """
    label = re.sub(r"\s+", "", fact["label"])
    quantity = fact["value"] + fact.get("unit", "")
    for block in blocks:
        normalized = re.sub(r"\s+", "", block).replace("：", ":")
        if fact.get("context") and not exact_present(fact["context"], block):
            continue
        for phrase in (label + quantity, label + ":" + quantity, quantity + label):
            if exact_present(phrase, normalized):
                return True
    return False


def semantic_review_issues(
    spec: dict[str, Any], review: dict[str, Any], actual: list[str], notes: dict[int, str],
    visual_elements: dict[int, set[str]] | None = None,
) -> list[dict[str, Any]]:
    """Validate the independent critic's per-requirement decisions against artifact text.

    Presence of the quoted artifact excerpt is checked deterministically; entailment
    remains the critic's responsibility. A builder's mapping is never accepted here.
    """
    issues: list[dict[str, Any]] = []
    reviewed = {item.get("slide"): item for item in review.get("slides", []) if isinstance(item, dict) and isinstance(item.get("slide"), int)}
    for index, slide in enumerate(spec.get("slides", []), 1):
        requirements = semantic_requirements(slide)
        if requirements is None:
            continue
        decisions = reviewed.get(index, {}).get("semantic_coverage", [])
        decisions = decisions if isinstance(decisions, list) else []
        by_id = {item.get("id"): item for item in decisions if isinstance(item, dict) and isinstance(item.get("id"), str)}
        expected_ids = {item["id"] for item in requirements.get("must_convey", [])}
        if len(by_id) != len(decisions) or set(by_id) != expected_ids:
            issues.append({"slide": index, "severity": "major", "code": "semantic_review_incomplete"})
        for required in requirements.get("must_convey", []):
            decision = by_id.get(required["id"], {})
            location = required.get("placement", "slide")
            text = notes.get(index, "") if location == "notes" else (actual[index - 1] if index <= len(actual) else "")
            excerpt = str(decision.get("actual_excerpt") or "").strip()
            elements = decision.get("visual_elements") or []
            visual_bound = location == "slide" and isinstance(elements, list) and bool(elements) and all(isinstance(element, str) for element in elements) and set(elements) <= (visual_elements or {}).get(index, set())
            if decision.get("status") != "covered":
                issues.append({"slide": index, "severity": "major", "code": "semantic_requirement_missing_or_changed", "requirement": required["id"]})
            elif decision.get("placement") != location or not (visual_bound or (excerpt and exact_present(excerpt, text))):
                issues.append({"slide": index, "severity": "major", "code": "semantic_excerpt_unbound", "requirement": required["id"]})
    return issues
