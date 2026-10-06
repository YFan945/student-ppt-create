# Reference-Deck Ingestion (rebuild_from_source)

PPTAgent-style ingestion, v0.19: when rebuilding from a GOOD reference deck,
**inherit its structure instead of reinventing it**. The analyzer reads the
reference PPTX read-only and extracts, per slide, a functional type plus the
layout signals that justify it; `plan` feeds the suggestions into the scaffold
so pages start from the reference's composition.

## Contract

```bash
# 1. Analyze a reference deck (read-only; never modifies the source)
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/reference_deck_analysis.py" \
  --pptx "<reference.pptx>" \
  --output "<work-dir>/reference-deck-analysis.json"

# 2. Plan with the analysis (rebuild_from_source; optional but recommended)
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan \
  --work-dir <wd> --slide-spec <compiled> --validation-report <report> \
  --art-direction <ad> --reference-analysis <work-dir>/reference-deck-analysis.json
```

## What the analyzer extracts

Per slide: `detected_type` (cover / section / data / comparison / process /
quote / references / closing / image-led / content-text), `confidence`,
`signals` (the evidence: first-slide, chart-or-table, image-covers-72%,
3-column-text, sparse-large-title…), `title_text`, text density, and
`suggested_archetypes` — an ordered list of layout-library ids validated at
read time (unknown ids are rejected by `plan`).

Detection precedence: cover (first slide) → references cues → **chart/table
evidence** → closing cues → sparse-large-title (section) → image-led →
comparison → process → quote → content-text. Chart/table outranks closing
cues because the chart takeaway panel's default English text contains
"conclusion".

## What plan does with it

- Validates the report shape and archetype vocabulary (refusal names the error).
- Records the file in `manifest.inputs.reference_analysis` (hash-bound).
- Scaffold uses each slide's first valid suggestion as the archetype-selection
  hint (the spec's own `layout` field stays in the spec; the suggestion wins at
  equal weight because the engine scores an explicit `layout` request +40).
- `manifest.reference_guidance.slides_guided` counts how many pages were
  guided — visible in the stage summary.

## Boundaries

- Suggestions are **advisory inputs to the engine**, not overrides: capacity,
  contraindications and fallback chains still apply, and the deterministic
  calibration gates + the single production review keep their authority over
  the visual system.
- The analyzer never reads or modifies the reference deck's media; images are
  the image-strategy contract's business, not ingestion's.
- `edit_ooxml` does not use this route (it preserves the source file directly);
  ingestion is for `rebuild_from_source` where the reference's structure — not
  its bytes — carries over.
