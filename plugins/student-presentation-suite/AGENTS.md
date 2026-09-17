# Student Presentation Suite — Plugin Agent Guide

Marketplace publish source, CI, and release steps live in the repository-root
[`AGENTS.md`](../../AGENTS.md). This file is **plugin-local** only. If the two
disagree on install/publish, the root file wins.

## Documentation Ownership (plugin)

| File | Job |
| --- | --- |
| `README.md` / `README-zh.md` | What the installed plugin does: pipeline, skills, intake, handoff, outputs, visual system, gates, runtime CLI. Point install/update at `../../README.md`. |
| `skills/*/SKILL.md` | Trigger, responsibility, state steps, output contract. Keep short; do not paste README chapters. |
| `references/*.md` and schemas | Canonical policy (intake, brief, Slide Spec, research, cost, images). |
| `examples/*/README.md` | How to run that example, nothing else. |
| Root `AGENTS.md` / `CLAUDE.md` | Repo-wide rules; do not duplicate them here. |

Changing a skill contract: update that `SKILL.md`, the owning `references/` file,
plugin README if the user-facing pipeline description changes, and tests. Do not
also paste the new rule into the marketplace README.

## Plugin Purpose

University presentation evidence gathering, planning, PPTX generation, and
review suite for student-owned academic contexts.

## Component Overview

| Component | Location | Purpose |
|-----------|----------|---------|
| Skills (×4) | `skills/` | Auto-activating: research, planning, PPTX production, review |
| Shared modules | `shared/` | Python validation, runtime, quality |
| Scripts | `scripts/` | CLI tools: pipeline, workflow guard, validation, generation, QA |
| References | `references/` | Canonical contracts: intake, brief, slide-spec, research, cost, images, design tokens |
| Tests | `tests/` | Python unittest suite |

## Skill Activation Rules

The four skills MUST only activate when BOTH conditions hold:
1. A clearly student-owned academic context (student, university assignment,
   classroom report, thesis/course defense, teacher rubric, or student competition)
2. An explicit PPT-related intent: outline, editable PPTX, review of an existing
   deck, **or** external evidence / Research Pack for such a deck

- **`sp-research`**: User needs external facts, current data, statistics,
  citations, or scope-D user materials compiled into a Research Pack. Never
  designs slides or creates PPTX files.
- **`sp-outline`**: User asks for PPT/slide outline or Slide Spec
  handoff. Never creates PPTX files.
- **`sp-deck`**: User asks to create, edit, improve, or
  rebuild an editable PPT/PPTX/PowerPoint/slide deck.
- **`sp-review`**: User provides an existing artifact and
  asks for review, scoring, risk checks, or comparison.

See `references/shared-standards.md` for full intent routing rules.

## Workflow State Machine

```
intake_pending → intake_confirmed → planned → producing → qa → complete
                      ↓               ↓          ↓          ↓       ↓
                    blocked         blocked    blocked    blocked   blocked
                    incomplete      incomplete incomplete incomplete incomplete

Terminal states (`blocked`/`incomplete`) may be entered from `intake_confirmed`
onward, not from `intake_pending`.
qa → producing is the rework edge (`ppt_pipeline.py repair`);
`incomplete → qa` is the recovery edge.
```

- `scripts/workflow_guard.py` owns intake only (`init` / `confirm`). `blocked`
  recovers with `unblock`.
- After `ppt_pipeline.py plan`, `build-manifest.json` is the production
  authority; the pipeline mirrors `workflow-state.json`. Do not call
  `workflow_guard.py transition` to advance `producing` or `complete`.
- Rework: `skills/sp-deck/scripts/ppt_pipeline.py repair --work-dir <wd>`.
  Delivery: `ppt_pipeline.py complete --work-dir <wd>`. Dispatch with `next`.

## Key Constraints

- Output directory: `${CLAUDE_PROJECT_DIR}/outputs` (never plugin install dir)
- Source decks are read-only; never overwritten
- Chinese body ≥ 22pt, English body ≥ 20pt, titles ≥ 24pt
- ≤ 4 bullets per slide, ≤ 80 Chinese chars or 40 English words
- Avoid AI boilerplate wording patterns

## Development

```bash
# Run all tests
cd plugins/student-presentation-suite
PYTHONPATH=. python -m unittest discover -s tests

# Code quality
ruff check shared/ scripts/ skills/ tests/
npx eslint scripts/*.js
npx prettier --check scripts/*.js

# PPTX environment check
node scripts/run_with_pptxgenjs.js --probe
```

## Dependencies

- Python: `requirements.txt` + `requirements-claude-pptx.txt`
- Node.js: `package.json` (pptxgenjs)
- System: LibreOffice (rendering), Poppler (page images), .NET SDK (Open XML validation)
