# Repository Guidelines

## Repository Purpose

This repository is the Claude Code-only marketplace for
`student-presentation-suite`. The publishable source of truth is the
`claude-code` branch of `YFan945/Personal-Student`.

Never publish this marketplace from or to `main`. The `main` branch is a
separate Codex implementation line with different manifests and runtime
dependencies.

## Repository Layout

- `.claude-plugin/marketplace.json`: marketplace manifest and published plugin version.
- `.github/workflows/validate.yml`: Windows/Linux tests and strict Claude validation.
- `.github/dependabot.yml`: automated dependency updates for pip, npm, and GitHub Actions.
- `.editorconfig`: cross-editor formatting baseline (indentation, line endings).
- `plugins/student-presentation-suite/`: complete installable Claude Code plugin.
- `scripts/install_claude_plugin.ps1`: install, migrate, update, and dependency setup.
- `scripts/check_marketplace_release.py`: repository-level release validation.
- `README.md` / `README-zh.md`: marketplace installation and contributor documentation.
- `CHANGELOG.md`: newest-first version release history.
- `CLAUDE.md`: project-specific conventions for Claude Code sessions.
- `CONTRIBUTING.md`, `SECURITY.md`: community and security guidelines.
- `plugins/student-presentation-suite/references/pptx-runtime-provenance.md`: runtime ownership and upstream audit provenance.

Inside the plugin package:

- `.claude-plugin/plugin.json`: plugin manifest.
- `skills/`: the three user-facing skill entrypoints and task-specific references.
- `references/`: shared intake, standards, image policy, and Slide Spec contracts.
- `scripts/`: environment checks, schema bridge, validation, and PPTX smoke tooling.
- `shared/`: reusable Python implementation.
- `tests/`: behavioral, schema, runtime, and delivery contracts.
- `examples/`: routing and interaction examples.

## Architecture And Ownership

The suite has three skills with non-overlapping outcomes:

- `student-presentation`: outline and speaking-plan work; never creates PPTX files.
- `student-presentation-review`: read-only diagnosis by default.
- `student-presentation-ppt`: editable PPTX creation and existing-deck improvement.

Canonical ownership:

- `references/presentation-intake.md`: clarification gate and workflow states.
- `references/shared-standards.md`: routing and presentation quality standards.
- `references/slide-spec.md` plus schema: structured planning and review-to-edit handoff.
- `references/presentation-brief.md` plus schema: scenario, audience, structure, interaction, and generation controls.
- `references/content-workflow.md`: layered content generation and narrative checks.
- `references/evidence-and-citations.md`: source ledger and citation policy.
- `references/revision-training-export.md`: locking, revisions, rehearsal, scoring, and export boundaries.
- `references/image-strategy.md`: image sourcing and visual policy.
- `shared/pptx_runtime/cjk_fonts.py` + `pptx_tool.py cjk-fonts`: post-process generated decks
- `shared/pptx_runtime/fetch_images.py` + `pptx_tool.py fetch-images`: execute the
  image-sources.json contract (permission gates enforced, provenance recorded).
- `shared/pptx_runtime/visual_baseline.py` + `pptx_tool.py visual-baseline`: perceptual-hash
  record/compare of rendered pages as a visual-regression defence.
- normalize also repairs pptxgenjs rich-text (stray per-run `<a:pPr>`), so multi-run
  inline emphasis is now valid and validated.  to add `<a:ea>` East Asian typefaces (CJK typography pairing lives in design-tokens.json).
- `references/image-sourcing.md` plus `image-sources.schema.json`: explicit image search/generation capability declaration, permission gate, and provenance recording.
- `references/design-tokens.json`: 12 style palettes, each with a light six-role palette and the matching dark scheme for cover/section/closing pages; `shared/design_tokens.py` owns dark-companion derivation and contrast floors.
- PPTX skill references: production mechanics and visual style controls.

Keep each `SKILL.md` compact. Entry files should define trigger, responsibility,
state transition, core workflow, and output contract. Put detailed rules in
selectively loaded references and prevent duplicated policy from drifting.

## Required Behavior

PPTX creation and editing use this state sequence:

`intake_pending → intake_confirmed → planned → producing → qa → complete`

While `intake_pending`, the skill may inspect supplied files and gather
requirements, but must not run generation, rendering, environment, or delivery
commands. The user must approve a complete Production Summary before production.

Review-only requests must not modify the source artifact. Existing-deck edits
must preserve the original and use the structured fields `source_deck`,
`edit_intent`, `review_findings`, `preserve`, and `change_summary_required`.

User deliverables belong in `${CLAUDE_PROJECT_DIR}/outputs` or the active
project's `outputs/` fallback. Never write generated decks into the installed
plugin or marketplace repository.

## Claude-Only Boundary

Do not add:

- `.codex-plugin`
- `agents/openai.yaml`
- `artifact-tool`
- Codex presentation runtime dependencies
- generated `.pptx`, `.png`, cache, or `node_modules` files

PPTX production uses the suite-owned `scripts/pptx_tool.py` facade,
`shared/pptx_runtime/`, and the task-specific references under the PPTX skill.
Do not restore the removed external `document-skills` dependency or copied runtime.

## Editing Rules

- Update both English and Chinese README files when behavior, installation,
  architecture, requirements, or release procedures change.
- Update `CHANGELOG.md` for every release-worthy change.
- Use `python plugins/student-presentation-suite/scripts/bump_version.py <version>` to
  synchronize all version fields (marketplace.json, plugin.json, package.json,
  package-lock.json). Run `--dry-run` first to preview.
- Update schema, bridge, documentation, examples, and tests together when
  changing Slide Spec fields or workflow contracts.
- Run `ruff check` on Python code and `npx eslint` + `npx prettier --check` on
  JavaScript code before committing.
- Never overwrite unrelated user changes in a dirty worktree.

## Validation

Install linting tools first:

```powershell
python -m pip install ruff
```

Then run from the repository root:

```powershell
python -m pip install -r plugins/student-presentation-suite/requirements.txt
python -m pip install -r plugins/student-presentation-suite/requirements-claude-pptx.txt
npm --prefix plugins/student-presentation-suite ci
$env:PYTHONPATH=(Resolve-Path "plugins/student-presentation-suite").Path

# Lint checks
ruff check plugins/student-presentation-suite/shared/ plugins/student-presentation-suite/scripts/ plugins/student-presentation-suite/tests/
npx --prefix plugins/student-presentation-suite eslint plugins/student-presentation-suite/scripts/*.js
npx --prefix plugins/student-presentation-suite prettier --check plugins/student-presentation-suite/scripts/*.js

# Unit and integration tests
python -m unittest discover -s plugins/student-presentation-suite/tests

# Runtime checks
python plugins/student-presentation-suite/scripts/smoke_pptx.py
python plugins/student-presentation-suite/scripts/check_plugin_release.py --json
python scripts/check_marketplace_release.py --json
python plugins/student-presentation-suite/scripts/check_claude_pptx_env.py --json --strict

# Claude manifest validation
claude plugin validate --strict .\plugins\student-presentation-suite
claude plugin validate --strict .
git diff --check
```

All checks must pass before publishing. The CI pipeline also runs
`pip-audit` and `npm audit` for dependency vulnerability scanning.
The environment check reports LibreOffice and Poppler as recommended for candidate
generation but required for rendered QA and `complete` delivery. Required runtime
dependencies are mode-specific; use `--mode create`, `edit_ooxml`, or
`rebuild_from_source` when diagnosing a workflow.

## Release Procedure

1. Confirm the current branch is `claude-code`.
2. Review the complete worktree diff and exclude unrelated files.
3. Run `python plugins/student-presentation-suite/scripts/bump_version.py <version>`
   to synchronize all version fields.
4. Update documentation and `CHANGELOG.md`.
5. Run the full validation suite.
6. Commit the release changes and **push directly to `claude-code`**.
7. Delete any temporary or release branches; keep only `main` and `claude-code`.
8. Verify the remote `claude-code` SHA and create the release tag.

Only the repository owner may push directly to `claude-code`. All other contributors
must open a pull request from a fork or topic branch and pass the required status
checks before merging.

Do not merge or push these Claude Code plugin changes to `main`.
