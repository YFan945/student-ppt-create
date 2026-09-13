#!/usr/bin/env python3
"""Retrieve positive visual composition priors for v0.8 slide generation.

The reference library is deliberately small and curated. This selector is not a
beauty model: it narrows the search space to composition recipes that match the
slide's narrative role, design grammar and visual strategy while avoiding recent
silhouette repetition. The model still adapts the selected references to content.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_LIBRARY = HERE.parent / "references" / "visual-reference-library.json"


def load_library(path: Path = DEFAULT_LIBRARY) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("references"), list):
        raise ValueError("Visual reference library must contain a references array.")
    return value


def normalize(value: str | None) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def normalize_list(values: list[str] | None) -> list[str]:
    return [normalize(item) for item in (values or []) if normalize(item)]


def score_reference(
    ref: dict[str, Any],
    *,
    role: str,
    grammar: str,
    visual_strategy: str,
    density: str,
    tags: list[str],
    history_ids: list[str],
    history_silhouettes: list[str],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    roles = normalize_list(ref.get("roles"))
    grammars = normalize_list(ref.get("grammars"))
    strategies = normalize_list(ref.get("visual_strategies"))
    ref_tags = set(normalize_list(ref.get("tags")))
    ref_density = normalize(ref.get("density"))
    ref_id = normalize(ref.get("id"))
    silhouette = normalize(ref.get("silhouette"))

    if role and role in roles:
        score += 7
        reasons.append("role")
    elif role and roles:
        score -= 2

    if grammar and grammar in grammars:
        score += 6
        reasons.append("grammar")
    elif grammar and grammars:
        score -= 1

    if visual_strategy and visual_strategy in strategies:
        score += 8
        reasons.append("visual-strategy")
    elif visual_strategy and strategies:
        score -= 2

    if density and density == ref_density:
        score += 2
        reasons.append("density")

    overlap = ref_tags.intersection(tags)
    if overlap:
        score += min(9, 3 * len(overlap))
        reasons.append("tags:" + ",".join(sorted(overlap)))

    if history_ids and ref_id == normalize(history_ids[-1]):
        score -= 20
    elif ref_id in {normalize(item) for item in history_ids[-4:]}:
        score -= 7

    if history_silhouettes and silhouette == normalize(history_silhouettes[-1]):
        score -= 8
    if len(history_silhouettes) >= 2 and silhouette and all(
        silhouette == normalize(item) for item in history_silhouettes[-2:]
    ):
        score -= 25

    # Positive-prior tie breakers: decisive focal ownership and explicit rationale.
    focal = ref.get("focal_share")
    if isinstance(focal, (int, float)) and 0.4 <= float(focal) <= 0.72:
        score += 1.5
    if str(ref.get("why_it_works") or "").strip():
        score += 0.5

    return score, reasons


def select_references(
    library: dict[str, Any],
    *,
    role: str = "",
    grammar: str = "",
    visual_strategy: str = "",
    density: str = "",
    tags: list[str] | None = None,
    history_ids: list[str] | None = None,
    history_silhouettes: list[str] | None = None,
    count: int = 3,
) -> list[dict[str, Any]]:
    normalized_tags = normalize_list(tags)
    ranked: list[tuple[float, str, list[str], dict[str, Any]]] = []
    for ref in library.get("references", []):
        if not isinstance(ref, dict) or not ref.get("id"):
            continue
        score, reasons = score_reference(
            ref,
            role=normalize(role),
            grammar=normalize(grammar),
            visual_strategy=normalize(visual_strategy),
            density=normalize(density),
            tags=normalized_tags,
            history_ids=history_ids or [],
            history_silhouettes=history_silhouettes or [],
        )
        ranked.append((score, str(ref["id"]), reasons, ref))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    used_silhouettes: set[str] = set()

    # First pass favors distinct silhouettes so the model sees genuinely different ideas.
    for score, _, reasons, ref in ranked:
        silhouette = normalize(ref.get("silhouette"))
        if silhouette and silhouette in used_silhouettes:
            continue
        selected.append({**ref, "retrieval_score": round(score, 3), "match_reasons": reasons})
        used_silhouettes.add(silhouette)
        if len(selected) >= max(1, count):
            return selected

    for score, _, reasons, ref in ranked:
        if any(item.get("id") == ref.get("id") for item in selected):
            continue
        selected.append({**ref, "retrieval_score": round(score, 3), "match_reasons": reasons})
        if len(selected) >= max(1, count):
            break
    return selected


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--role", default="")
    parser.add_argument("--grammar", default="")
    parser.add_argument("--visual-strategy", default="")
    parser.add_argument("--density", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--history-ids", default="")
    parser.add_argument("--history-silhouettes", default="")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    selected = select_references(
        load_library(args.library),
        role=args.role,
        grammar=args.grammar,
        visual_strategy=args.visual_strategy,
        density=args.density,
        tags=split_csv(args.tags),
        history_ids=split_csv(args.history_ids),
        history_silhouettes=split_csv(args.history_silhouettes),
        count=args.count,
    )
    payload = {
        "version": "0.8",
        "query": {
            "role": args.role,
            "grammar": args.grammar,
            "visual_strategy": args.visual_strategy,
            "density": args.density,
            "tags": split_csv(args.tags),
        },
        "selected": selected,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    if args.json or not args.output:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
