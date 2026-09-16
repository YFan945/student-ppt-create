# Student Presentation Suite — Plugin Agent Guide

## Plugin Purpose

University presentation planning, PPTX generation, and review suite for
student-owned academic contexts.

## Component Overview

| Component | Location | Purpose |
|-----------|----------|---------|
| Skills (×4) | `skills/` | Auto-activating: planning, PPTX production, review |
| Shared modules | `shared/` | Python validation, runtime, quality |
| Scripts | `scripts/` | CLI tools: workflow guard, validation, generation, QA |
| References | `references/` | Canonical contracts: intake, brief, slide-spec, design tokens |
| Tests | `tests/` | Python unittest suite |

## Skill Activation Rules

The four skills MUST only activate when BOTH conditions hold:
1. A clearly student-owned academic context (student, university assignment,
   classroom report, thesis/course defense, teacher rubric, or student competition)
2. An explicit PPT intent

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
qa → producing is the rework edge; `incomplete → qa` is the recovery edge
(`transition --reason <summary>`).
```

- Full intake gate is a workflow convention tracked by `scripts/workflow_guard.py`
- `scripts/workflow_guard.py` persists and tracks the workflow state

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
