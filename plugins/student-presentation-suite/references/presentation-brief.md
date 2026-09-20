# Presentation Brief

The Presentation Brief is the confirmed global control plane. It answers what
the presentation is for and how it should be produced. Slide Spec answers what
each slide contains.

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
- `mixed`: keep the main story accessible and move specialist detail to notes or appendix.

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

Choose one of the 12 formal lightweight references in `visual-style-menu.md`, or set
`visual_style: Other`. A formal reference supplies only style character, six palette roles,
cover/content/section/closing background references, and one optional SVG reference. It does not
control layout, shapes, images, charts, components, or page rhythm.

`Other` requires `visual_style_custom` with `style_character`, all six `palette` roles, all four
`backgrounds`, and `svg_reference.name` plus `svg_reference.usage`. The AI may complete missing
values from the topic and user direction, but all four sections must appear in the Production
Summary and be confirmed before planning.

## Quality Levels

- `basic`: complete, readable, correctly timed, and easy to present.
- `high-score`: additionally optimize rubric alignment, evidence chain,
  distinctive opening, limitations, teacher/judge questions, and rehearsal.

Validate a saved brief with:

```powershell
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_presentation_brief.py" brief.yaml --json
```
