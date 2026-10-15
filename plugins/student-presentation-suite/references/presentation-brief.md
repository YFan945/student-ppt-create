# Presentation Brief

## New-task policy (2.1)

For new tasks, [model-led-design.md](model-led-design.md) owns design modes, frozen semantic
requirements and measured text. Its policy overrides legacy template/scale/
verbatim-copy guidance below. `auto` is the default; user brand/template/logo
and actual readability remain binding. Treat fixed sizes, proportions and
gallery treatments here as optional design suggestions for new tasks.


The Presentation Brief is an optional reusable record of global controls. For a normal deck, the approved summary and Slide Spec meta are sufficient; do not create another copy. A supplied or reused Brief must agree with the approved summary. Slide Spec owns per-page content.

## Scenario Classification

Classify the request into exactly one primary scenario:

| Scenario | Default structure | Evaluation emphasis |
| --- | --- | --- |
| `coursework` | background → question → analysis → evidence → conclusion | course understanding and clarity |
| `defense` | problem → method → implementation → results → contribution → limitation | evidence, ownership, and defensibility |
| `competition` | pain point → solution → implementation → validation → value → feasibility | differentiation and measurable value |
| `club-showcase` | purpose → activities → outcomes → participant story → next action | participation and visible outcomes |
| `research` | question → related context → method → results → interpretation → limitation | method and evidence quality |

If two scenarios apply, choose the one that determines scoring and record the
other in `course` or `rubric`.

## Audience Model

- `teacher`: connect claims to course concepts, rubric, evidence, and limits.
- `classmates`: explain necessary concepts and use relatable examples.
- `judges`: lead with differentiation, proof, feasibility, and risks.
- `non-specialists`: reduce jargon and explain why each technical detail matters.
- `mixed`: keep the reading focus accessible while preserving useful specialist detail on the page; optional supplementary material may use an allowed appendix. Notes selectively explain the highlights.

Depth controls terminology and explanation:

- `introductory`: define essential terms and use concrete examples.
- `standard`: assume course-level knowledge and explain key decisions.
- `expert`: compress basics and expose method, assumptions, tradeoffs, and evidence.

## Interaction Modes

- `beginner`: show recommendations, impacts, and the complete Production Summary.
- `expert`: reuse supplied constraints and ask only unresolved decisions that can
  materially change structure, evidence, visual direction, or deliverables.

Both modes require explicit Production Summary approval before PPTX production.

## Deliverables

`deliverables` is the user-confirmed set, and it is the only thing that decides
what gets handed over. Render pages, the contact sheet, and the QA reports are
pipeline evidence and are never implied deliverables; embedded speaker notes are
controlled by Slide Spec `meta.include_speaker_notes`, not by this field. See
`presentation-intake.md` § "Deliverables vs. pipeline evidence" for the full
boundary — do not restate it here.

## Visual Style Reference

New student work aims for content-rich, varied visual expression and layered color, with free composition. Word/character controls are optional: record them only when the user confirms a cap, and preserve supplied constraints. See `model-led-design.md` for the canonical new-task policy.

Choose one of the 12 formal lightweight references in `visual-style-menu.md`, or set
`visual_style: Other`. A formal reference supplies style character, palette roles and font families;
custom background/SVG preferences are optional. It does not
control layout, shapes, images, charts, components, or page rhythm.

`Other` requires `visual_style_custom` with `style_character` and the six base `palette` roles.
Additional semantic colors are allowed. `backgrounds` is optional and may describe only used
page kinds; `svg_reference` is optional, with `name` and `usage` required when supplied. A dark
palette may be supplied or derived. Confirm the actual visual direction, without inventing
unused backgrounds or motifs. Word/character caps accept any positive integer when requested.

## Quality Levels

Canonical tiers (`fast` / `standard` / `rigorous`) live in `quality_tiers.py`;
`basic` and `high-score` are accepted legacy aliases.

All tiers require factual correctness, current full-page renders, visual inspection and selected deliverables; fast never skips those checks.

- `fast` (legacy `basic`): directly author from supplied material; inspect all final pages and repair actual problems.
- `standard`: also compare the relevant full-page reference when available, check non-adjacent repetition and compare visible content with the selective speaking path.
- `rigorous` (legacy `high-score`): also trace important claims/numeric associations to source, examine the most difficult page at full and reduced scale, and test likely audience questions against evidence. Consider an internal alternative composition only when the current page fails its communication purpose; do not generate alternatives by quota. Check editability and template preservation when applicable. Rehearsal/export stays within the confirmed scope.

Record concrete page findings in the existing review-note when useful. These are author actions, not new agent stages, aesthetic score gates or independent verification.

Validate a saved brief with:

```powershell
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_presentation_brief.py" brief.yaml --json
```

`output_dir` selects a delivery directory inside the active project outputs tree; carry it to Slide Spec `meta.output_dir`. New production defaults to `outputs/<work-id>`. Preview exports all slides, while contact-sheet is the overview.
