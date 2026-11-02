"""Cross-field validation for Student Presentation Slide Spec data."""

from __future__ import annotations

from typing import Any

SCENARIO_REQUIRED_ROLE_GROUPS: dict[str, tuple[tuple[str, ...], ...]] = {
    "coursework": (("background", "problem"), ("method",), ("evidence", "result"), ("conclusion", "closing")),
    "defense": (("problem",), ("method",), ("result", "evidence"), ("solution", "value"), ("limitation",), ("qa",)),
    "competition": (("problem",), ("solution",), ("method",), ("result", "evidence"), ("value",), ("limitation",)),
    "club-showcase": (("opening", "background"), ("method",), ("result", "evidence"), ("value", "closing")),
    "research": (("problem",), ("background",), ("method",), ("result", "evidence"), ("limitation",), ("conclusion", "closing")),
}


def _validate_scenario_roles(meta: dict[str, Any], slides: list[Any]) -> list[dict[str, str]]:
    scenario = meta.get("scenario")
    required = SCENARIO_REQUIRED_ROLE_GROUPS.get(scenario)
    if not required:
        return []
    roles = [slide.get("role") for slide in slides if isinstance(slide, dict) and slide.get("role")]
    errors: list[dict[str, str]] = []
    if not roles:
        return [{"path": ".slides", "message": f"scenario={scenario} requires story roles on slides"}]
    for alternatives in required:
        if not any(role in alternatives for role in roles):
            errors.append({
                "path": ".slides",
                "message": f"scenario={scenario} requires one of story roles: {', '.join(alternatives)}",
            })
    final_indices = [index for index, slide in enumerate(slides) if isinstance(slide, dict) and slide.get("role") in {"conclusion", "closing"}]
    if final_indices:
        first_final = min(final_indices)
        late_core = [
            str(slide.get("role"))
            for slide in slides[first_final + 1:]
            if isinstance(slide, dict) and slide.get("role") in {"background", "problem", "method", "evidence", "result", "solution", "value"}
        ]
        if late_core:
            errors.append({"path": ".slides", "message": "core story roles cannot follow conclusion/closing: " + ", ".join(late_core)})
    return errors


def _validate_visual_semantics(slides: list[Any]) -> list[dict[str, str]]:
    """Validate supplied numeric data, never demand a duplicate visual plan."""
    errors: list[dict[str, str]] = []
    for index, slide in enumerate(slides):
        visual = slide.get("visual") if isinstance(slide, dict) else None
        details = visual.get("details") if isinstance(visual, dict) else None
        series = details.get("series") if isinstance(details, dict) else None
        if not isinstance(series, list):
            continue
        for number, item in enumerate(series):
            if not isinstance(item, dict):
                continue
            labels, values = item.get("labels"), item.get("values")
            target = f".slides.{index}.visual.details.series.{number}"
            if isinstance(values, list) and any(value is not None and
                    (isinstance(value, bool) or not isinstance(value, (int, float))) for value in values):
                errors.append({"path": target + ".values", "message": "chart values must be numeric or null", "severity": "error"})
            if isinstance(labels, list) and isinstance(values, list) and len(labels) != len(values):
                errors.append({"path": target, "message": "chart labels and values must have equal length", "severity": "error"})
    return errors


def semantic_errors(data: Any) -> list[dict[str, str]]:
    """Return semantic errors that JSON Schema cannot express clearly."""
    if not isinstance(data, dict):
        return []

    errors: list[dict[str, str]] = []
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    slides = data.get("slides") if isinstance(data.get("slides"), list) else []
    sources = data.get("template_sources") or []
    source_ids = [item["id"] for item in sources]
    if len(source_ids) != len(set(source_ids)):
        errors.append({"path": ".template_sources", "message": "template source ids must be unique"})
    for index, slide in enumerate(slides):
        for ref in slide.get("template_refs", []):
            if ref["source_id"] not in source_ids:
                errors.append({"path": f".slides.{index}.template_refs", "message": f"unknown template source: {ref['source_id']}"})

    if slides:
        ids = [slide.get("id") for slide in slides if isinstance(slide, dict)]
        if len(ids) != len(set(ids)):
            errors.append({"path": ".slides", "message": "slide ids must be unique"})

    # Timing, ownership and visual strategy are planning aids. They cannot
    # certify the actual rendered artifact and do not block free-page authoring.
    visual_findings = _validate_visual_semantics(slides)
    errors.extend({"path": item["path"], "message": item["message"]}
                  for item in visual_findings if item.get("severity") == "error")

    revision_operation = data.get("revision_operation")
    if revision_operation in {"rewrite-slide", "compress", "expand", "add-evidence"}:
        targets = data.get("target_slides")
        if not isinstance(targets, list) or not targets:
            errors.append({"path": ".target_slides", "message": f"{revision_operation} requires at least one target slide"})
    if revision_operation == "rewrite-section" and not data.get("target_section"):
        errors.append({"path": ".target_section", "message": "rewrite-section requires target_section"})

    evidence = data.get("evidence_ledger")
    if isinstance(evidence, list):
        evidence_ids = [item.get("id") for item in evidence if isinstance(item, dict) and isinstance(item.get("id"), str)]
        duplicates = sorted({item for item in evidence_ids if evidence_ids.count(item) > 1})
        if duplicates:
            errors.append({"path": ".evidence_ledger", "message": "evidence ids must be unique: " + ", ".join(duplicates)})
        known = set(evidence_ids)
        for index, slide in enumerate(slides):
            if not isinstance(slide, dict):
                continue
            refs = slide.get("evidence_refs")
            if isinstance(refs, list):
                unknown = sorted({str(ref) for ref in refs if ref not in known})
                if unknown:
                    errors.append({"path": f".slides.{index}.evidence_refs", "message": "unknown evidence refs: " + ", ".join(unknown)})
            if slide.get("lock_reason") and not slide.get("locked"):
                errors.append({"path": f".slides.{index}.lock_reason", "message": "lock_reason requires locked=true"})

    for index, slide in enumerate(slides):
        semantic = slide.get("semantic_requirements")
        if not isinstance(semantic, dict):
            continue
        if data.get("schema_version") != "2.1":
            errors.append({"path": f".slides.{index}.semantic_requirements", "message": "semantic_requirements requires schema_version 2.1"})
        requirements = semantic.get("must_convey", [])
        facts = semantic.get("fact_bindings", [])
        fact_ids = [item["id"] for item in facts]
        if len(fact_ids) != len(set(fact_ids)):
            errors.append({"path": f".slides.{index}.semantic_requirements.fact_bindings", "message": "fact binding ids must be unique per page"})
        ids = [item["id"] for item in requirements]
        if len(ids) != len(set(ids)):
            errors.append({"path": f".slides.{index}.semantic_requirements", "message": "requirement ids must be unique per page"})
        # Same two-level contract as slide-level evidence_refs above: without a
        # top-level evidence_ledger the refs are Research Pack F/D/Q (or D-pack
        # source) ids awaiting --research-pack compilation, so existence is only
        # checkable once the spec carries its own ledger.
        ledger_present = isinstance(evidence, list)
        known = (
            {item.get("id") for item in evidence if isinstance(item, dict) and isinstance(item.get("id"), str)}
            if ledger_present
            else set()
        )
        for item in requirements:
            if ledger_present:
                unknown = sorted({str(ref) for ref in item.get("evidence_refs", []) if ref not in known})
                if unknown:
                    errors.append({
                        "path": f".slides.{index}.semantic_requirements.must_convey",
                        "message": "unknown semantic evidence refs: " + ", ".join(unknown),
                    })
            if item.get("placement") == "notes" and meta.get("include_speaker_notes") is False:
                errors.append({"path": f".slides.{index}.semantic_requirements", "message": "notes requirements require speaker notes"})

    improvement_fields = ("edit_intent", "review_findings", "preserve", "change_summary_required")
    present_improvement_fields = [field for field in improvement_fields if data.get(field) not in (None, False, [], "")]
    if present_improvement_fields and not data.get("source_deck"):
        errors.append({
            "path": ".source_deck",
            "message": "source_deck is required when using existing-deck improvement fields: " + ", ".join(present_improvement_fields),
        })

    return errors


def planning_warnings(data: Any) -> list[dict[str, str]]:
    """Explain planning inconsistencies without pretending they are defects."""
    if not isinstance(data, dict):
        return []
    meta, slides = data.get("meta") or {}, data.get("slides") or []
    warnings = []
    if meta.get("slide_count") is not None and meta["slide_count"] != len(slides):
        warnings.append({"path": ".meta.slide_count", "message": f"declared count {meta['slide_count']}; actual count {len(slides)} is used"})
    timings = [s.get("timing_sec") for s in slides if isinstance(s.get("timing_sec"), int)]
    if len(timings) == len(slides) and meta.get("duration_min"):
        expected = meta["duration_min"] * 60
        if abs(sum(timings) - expected) > max(60, expected * 0.35):
            warnings.append({"path": ".slides", "message": "estimated speaking times differ from the target; check pauses, demos and rehearsal"})
    members = meta.get("members") or []
    if meta.get("format") == "group":
        for index, slide in enumerate(slides):
            owner = slide.get("owner", "shared")
            if owner not in {*members, "shared"}:
                warnings.append({"path": f".slides.{index}.owner", "message": f"owner {owner!r} is not listed; shared ownership is allowed"})
    return warnings
