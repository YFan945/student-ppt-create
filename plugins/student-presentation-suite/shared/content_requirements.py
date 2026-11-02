"""Frozen information requirements shared by source checks, readback and critic."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import Any

# ASCII token boundaries intentionally allow adjoining Chinese characters.
NUMBER_RE = re.compile(r"(?<![\d.+-])[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?[%％]?(?!\d|\.\d|,\d|[%％])")


def notes_digest(notes: dict[int, str]) -> str:
    return hashlib.sha256(json.dumps(notes, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def semantic_binding(spec_sha256: str, actual: list[str], notes: dict[int, str]) -> dict[str, str]:
    return {"slide_spec_sha256": spec_sha256, "notes_sha256": notes_digest(notes), "text_sha256": hashlib.sha256(json.dumps(actual, ensure_ascii=False).encode("utf-8")).hexdigest()}


def numbers(text: str) -> list[str]:
    return sorted(set(NUMBER_RE.findall(text)))


def numeric_present(expected: str, actual: str) -> bool:
    """Compare numeric values and percent units without rounding or unit conversion.

    Exact quotations continue to use exact_present. Only numeric requirements
    and fact bindings accept grouping separators and full-width digits.
    """
    def value(token: str) -> tuple[Decimal, bool] | None:
        token = unicodedata.normalize("NFKC", token).replace(",", "")
        percent = token.endswith("%")
        try:
            return Decimal(token.removesuffix("%")), percent
        except InvalidOperation:
            return None

    wanted = value(expected)
    return wanted is not None and any(value(token) == wanted for token in numbers(unicodedata.normalize("NFKC", actual)))


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
    """Match an opted-in fact in a text object or a spatially associated region.

    Regions are assembled by the OOXML reader, never by joining a whole slide.
    A small positive connector vocabulary accepts natural sentences without
    treating negated, comparative or qualified claims as an exact fact.
    """
    label = unicodedata.normalize("NFKC", re.sub(r"\s+", "", fact["label"]))
    unit = re.sub(r"\s+", "", fact.get("unit", ""))
    for block in blocks:
        normalized = unicodedata.normalize("NFKC", re.sub(r"\s+", "", block))
        if fact.get("context") and not exact_present(fact["context"], block):
            continue
        for token in NUMBER_RE.finditer(normalized):
            if not numeric_present(fact["value"], token.group()):
                continue
            before, after = normalized[:token.start()], normalized[token.end():]
            if not after.startswith(unit):
                continue
            after = after[len(unit):]
            if unit and unit[-1].isascii() and unit[-1].isalpha() and after and after[0].isascii() and after[0].isalnum():
                continue
            connectors = r"(?:[:=]|为|是|达到|等于)?"
            if re.search(re.escape(label) + connectors + r"$", before) or after.startswith(label):
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
