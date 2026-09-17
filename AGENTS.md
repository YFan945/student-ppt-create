# Repository Guidelines

## Repository Purpose

This repository is the Claude Code-only marketplace for
`student-presentation-suite`. **The `main` branch of this repository
(`YFan945/student-ppt-create`) is the single publishable source of truth.**

The former `claude-code` branch of `YFan945/Personal-Student` is retired: do
not publish, install, or point documentation at it. Every manifest
(`homepage` / `repository`), the install script, and both READMEs must resolve
to `github.com/YFan945/student-ppt-create/tree/main` — `check_plugin_release.py`
enforces this so a silent rollback is impossible. Codex has its own separate
implementation line and is not supported here.

## Repository Layout

- `.claude-plugin/marketplace.json`: marketplace manifest and published plugin version.
- `.github/workflows/validate.yml`: Windows/Linux tests and strict Claude validation.
- `.github/dependabot.yml`: automated dependency updates for pip, npm, and GitHub Actions.
- `.editorconfig`: cross-editor formatting baseline (indentation, line endings).
- `plugins/student-presentation-suite/`: complete installable Claude Code plugin.
- `scripts/install_claude_plugin.ps1`: install, migrate, update, and dependency setup.
- `scripts/check_marketplace_release.py`: repository-level release validation.
- `README.md` / `README-zh.md`: marketplace only (install, verify, update, uninstall, troubleshooting). Plugin behavior lives in the plugin READMEs.
- `CHANGELOG.md`: newest-first version release history.
- `CLAUDE.md`: short pointer for Claude Code sessions; must not duplicate this file.
- `CONTRIBUTING.md`, `SECURITY.md`: community and security guidelines.
- `plugins/student-presentation-suite/references/pptx-runtime-provenance.md`: runtime ownership and upstream audit provenance.

Inside the plugin package:

- `.claude-plugin/plugin.json`: plugin manifest.
- `agents/`: plugin-scoped subagents. `presentation-researcher.md` is the isolated
  executor that `sp-research` spawns explicitly through the Agent tool, so raw
  retrieval never reaches the main conversation context. Do **not** reintroduce
  `context: fork` as the isolation mechanism: it is not honored under `claude -p`,
  where the skill is inlined into the main session. Plugin subagents register as
  `<plugin>:<agent>` and may not use `hooks`, `mcpServers`, or `permissionMode`.
- `skills/`: the four user-facing skill entrypoints and task-specific references.
- `references/`: shared intake, standards, cost discipline, image policy, and Slide Spec contracts.
- `scripts/`: environment checks, schema bridge, validation, session cost review, Research Pack
  validation, and PPTX smoke tooling.
- `skills/sp-deck/scripts/run_gates.py`: single-run orchestrator for the v0.8 visual gates; a passing
  run prints one line, and the full detail lands in `gates-report.json`. `run_gates.sh` only locates
  an interpreter — call the python form, which also works where `sh` resolves to WSL.
- `commands/sp-cost-report.md`: `/sp-cost-report` entrypoint for `scripts/session_cost.py`.
- `shared/`: reusable Python implementation.
- `tests/`: behavioral, schema, runtime, and delivery contracts.
- `examples/`: routing and interaction examples.

## Documentation Ownership

Keep **one owner per fact**. Copy-paste across READMEs is how `claude-code` vs
`main` drift happened. When you change a row's topic, update every file in
**Update together**; do not invent a fifth copy.

| Topic | Canonical file | Update together | Do not put it in |
| --- | --- | --- | --- |
| Install, marketplace add, migrate, verify, update, uninstall | root `README.md` | root `README-zh.md` | plugin README (link the root file) |
| Four skills, intake, handoff, visual system, gates, plugin CLI | `plugins/student-presentation-suite/README.md` | plugin `README-zh.md` | root README beyond a one-line pointer |
| Routing / quality / Slide Spec / research / cost rules | the matching `plugins/.../references/*.md` | `SKILL.md` only if trigger or workflow steps change | README prose restating the whole policy |
| Skill trigger, state transition, output contract | `skills/*/SKILL.md` | examples if routing examples change | `CLAUDE.md` |
| Publish source, validation commands, release, version bump | **this file** (`AGENTS.md`) | `CONTRIBUTING.md` if contributor steps change; `CHANGELOG.md` for user-visible releases | READMEs except “see AGENTS.md” |
| Plugin-local test commands and skill activation | `plugins/student-presentation-suite/AGENTS.md` | — | root `AGENTS.md` command blocks (keep one validation suite here) |
| Session bootstrap for Claude Code | `CLAUDE.md` | only if the pointer table changes | anywhere else |

Always:

- English and Chinese README pairs stay in sync. Never update only one language.
- `CHANGELOG.md`: add `## Unreleased` (or the version section) for release-worthy doc or behavior changes.
- Nested READMEs (`examples/golden-sample/`, `examples/visual-template-gallery/`, `scripts/live_prompts/`) describe **that directory only**.
- Historical notes (`CHANGELOG` past versions, `scripts/live_prompts/FINDINGS.md`) are not current install instructions.

## Architecture And Ownership

The suite has four skills with non-overlapping outcomes, wired as a pipeline:

```text
sp-research → sp-outline → sp-deck → sp-review
  evidence      content      build      review
```

- `sp-research`: evidence layer only — retrieve, grade, cross-check sources into a
  Research Pack. Never chooses layouts, designs pages, produces PPTX, or writes
  prose notes.
- `sp-outline`: outline and speaking-plan work; never creates PPTX files.
- `sp-review`: read-only diagnosis by default.
- `sp-deck`: editable PPTX creation and existing-deck improvement.

Canonical ownership:

- `references/presentation-intake.md`: clarification gate and workflow states.
- `references/shared-standards.md`: routing and presentation quality standards.
- `references/slide-spec.md` plus schema: structured planning and review-to-edit handoff.
- `references/presentation-brief.md` plus schema: scenario, audience, structure, interaction, and generation controls.
- `references/content-workflow.md`: layered content generation and narrative checks.
- `references/evidence-and-citations.md`: source ledger and citation policy.
- `references/revision-training-export.md`: locking, revisions, rehearsal, scoring, and export boundaries.
- `references/image-strategy.md`: image sourcing and visual policy.
- `references/research-workflow.md`: when and how external knowledge is gathered — A/B/C/D
  classification, source tiers, cross-validation, budget bands, and the Research Pack contract.
- `references/cost-discipline.md`: how the work is carried out — batched tool calls,
  in-place edits, write-once artifacts, per-stage summaries, delegated search, single-run gating.
- `references/visual-review.schema.json`: canonical shape of the critic's `visual-review.json`;
  QA validates against it before consuming. `required` is deliberately the minimal set the gate
  reads (`pptx_sha256`, `slides`) — fields nobody consumes must not become blocking requirements.
- `references/spawn-templates.md`: the fixed spawn prompts for the isolated agents
  (researcher / builder / critic). Fixed constraint blocks are copied verbatim and data slots carry
  paths only; byte-exact content (claims, source titles, numbers) is never transcribed into a prompt.
- `shared/pptx_runtime/cjk_fonts.py` + `pptx_tool.py cjk-fonts`: post-process generated decks
- `shared/pptx_runtime/fetch_images.py` + `pptx_tool.py fetch-images`: execute the
  image-sources.json contract (permission gates enforced, provenance recorded).
- `shared/pptx_runtime/visual_baseline.py` + `pptx_tool.py visual-baseline`: perceptual-hash
  record/compare of rendered pages as a visual-regression defence.
- normalize also repairs pptxgenjs rich-text (stray per-run `<a:pPr>`), so multi-run
  inline emphasis is now valid and validated.  to add `<a:ea>` East Asian typefaces (CJK typography pairing lives in design-tokens.json).
- `references/image-sourcing.md` plus `image-sources.schema.json`: explicit image search/generation capability declaration, permission gate, and provenance recording.
- `shared/image_capability.py`: whether this session can actually obtain imagery, resolved once for both readers — `check_claude_pptx_env.py` (environment status) and `art_direction_check.py` (refuses an `asset_plan` whose image visuals cannot be delivered).
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

- Follow **Documentation Ownership** above. Marketplace vs plugin README is a
  split of audience, not two copies of the same essay.
- Update both English and Chinese README files in the pair you actually touch
  (root pair and/or plugin pair) when that pair's topics change.
- Update `CHANGELOG.md` for every release-worthy change.
- Use `python plugins/student-presentation-suite/scripts/bump_version.py <version>` to
  synchronize all version fields (marketplace.json, plugin.json, package.json,
  package-lock.json). Run `--dry-run` first to preview.

### Version bump policy (owner's standing instruction)

**"更新版本号" 在本项目里与"打 tag + 建 GitHub Release"是同一个表述，两者完全等价。**
owner 说"更新版本号"时，完整动作固定为下面四步，缺一不可，**不要再就"要不要打 tag /
建 Release"二次询问**——那已经包含在这句话里了：

1. `bump_version.py <version>`（先 `--dry-run` 预览）
2. CHANGELOG 的 `## Unreleased` 改为 `## <version> — <date>`
3. 提交并推送
4. 创建 annotated tag `v<version>` 并 `gh release create` 建 GitHub Release

升哪一段按下表判断：

| 改动规模 | 要升哪一段 | 是否需要先问 |
| --- | --- | --- |
| 常规更新（补丁、小改、文档、内部重构） | **patch**（x.y.**Z**） | **不用问**，直接升 |
| 较大改动（新增能力 / 新增工具 / 新增对外规则） | **minor**（x.**Y**.0） | **必须先问** |
| 非常大（破坏性变更、契约或架构改变） | **major**（**X**.0.0） | **一定要问** |

也就是说：任何提交的默认动作都是自动升 patch；只有当你判断这次改动够得上"较大"或
"非常大"时，才停下来询问，不要自行升 minor 或 major。拿不准时按较小的一档处理，然后
把问题抛给 owner。（"是否升 minor / major"需要问；但"升完要不要打 tag / 建 Release"
不需要问。）
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
ruff check plugins/student-presentation-suite/shared/ plugins/student-presentation-suite/scripts/ plugins/student-presentation-suite/skills/ plugins/student-presentation-suite/tests/
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

1. Confirm the current branch is `main` — it is the single publishable source of truth.
2. Review the complete worktree diff and exclude unrelated files.
3. Run `python plugins/student-presentation-suite/scripts/bump_version.py <version>`
   to synchronize all version fields.
4. Update documentation and `CHANGELOG.md`.
5. Run the full validation suite.
6. Commit the release changes and **push directly to `main`**.
7. Wait for the exact main commit’s `validate` workflow and `release-ready` check to succeed. Then create an **annotated** tag `v<version>`. Lightweight tags are not used: every
   release tag except `v0.11.0` is annotated, and `v0.11.1` had to be re-tagged.
8. Create the GitHub Release, matching the existing title style:
   `gh release create v<version> --title "v<version> — <one-line theme>" --notes-file <file>`.

Only the repository owner may push directly to `main`. All other contributors
must open a pull request from a fork or topic branch and pass the required status
checks before merging.

Do not publish, install, or point documentation at the retired
`YFan945/Personal-Student` `claude-code` branch.
