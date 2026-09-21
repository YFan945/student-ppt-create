# Student Presentation Suite for Claude Code

[中文](README-zh.md) | English

**This file (plugin README):** what the installed plugin does — pipeline, four
skills, intake, handoff, outputs, visual system, quality gates, and runtime CLI.
Install, update, and uninstall belong in the repository-root
[README](../../README.md). Policy details belong in `references/` and `SKILL.md`.
Doc sync: repository [AGENTS.md](../../AGENTS.md) → Documentation Ownership;
plugin-local notes in [AGENTS.md](AGENTS.md).

`student-presentation-suite` is a Claude Code plugin for student-owned
university presentations. It separates evidence gathering, content planning,
editable PPTX production, and existing-deck review while sharing one intake,
Slide Spec, and quality contract.

This package is published from `YFan945/student-ppt-create` on **`main`**. See
the [root README](../../README.md) for installation.

Install ID: `student-presentation-suite@claude-personal`.

## Pipeline

```text
sp-research → sp-outline → sp-deck → sp-review
  evidence      content      build      review
```

## Skills

### `sp-research`

Owns the evidence layer only: decides which content actually needs external
support, retrieves high-quality sources, cross-checks numbers, grades each source
by tier, and emits a structured `research-pack.json` for the later skills to
consume.

The design brief is *Search for evidence, not text* — not "find me some slide
content", but "identify the claims that need evidence and settle them". It does
not choose layouts, design pages, produce PPTX, touch the visual direction, or
write prose speaker notes; mixing those responsibilities contaminates every
layer downstream.

It doubles as a context firewall — and that is a **mechanism**, not a prompt
convention: the main flow **spawns `agents/presentation-researcher.md` explicitly**
through the Agent tool (`subagent_type:
student-presentation-suite:presentation-researcher`, no `name`), so retrieval never
runs in the main conversation context. The subagent cannot see the conversation
history and the main flow never receives its search trail or raw pages (~100k
tokens in, ~8k out). Passing the work-id, brief path, scope and materials path in
the spawn prompt is required — the subagent reads neither the frontmatter
arguments nor the conversation. Sequencing is deliberate: research must finish
before `sp-outline` starts planning, so do not advance until the `RESEARCH_DONE`
envelope arrives.

An earlier revision relied on `context: fork` in this skill's frontmatter. That
mechanism is **not honored under `claude -p` (print mode)**: two live runs measured
`subagent_stats.spawned = 0` with no subagent event in the stream, and the main
session ended up running the researcher's own commands. Explicit spawn behaves the
same in interactive and print sessions, which is what makes the firewall a
mechanism rather than a convention.

The hop from Research Pack to Slide Spec is deterministic too:
`scripts/research_pack_to_evidence.py` compiles `evidence-map.json` by a fixed rule
(findings sorted by id, then data_points sorted by id, to `E01, E02, …`) rather
than letting the model hand-write ledger entries. Compiling the same pack twice
yields an identical ledger, and a pack that fails validation is refused outright.
`slide_spec_guard.py freeze` can bind the three hashes —
`research-pack.json`, its validation report, and `evidence-map.json` — into the
frozen lock; editing any of them afterwards makes `check` fail immediately.

Rules live in `references/research-workflow.md`, the output shape in
`references/research-pack.schema.json`, and `scripts/validate_research_pack.py`
enforces them — rejecting high-confidence claims resting on a single source,
fact claims supported only by tier D, conflicts that never lowered confidence,
and retrieval that failed silently instead of being recorded.

### `sp-outline`

Use for slide outlines, presentation spines, speaking notes, group allocation,
transitions, Q&A preparation, and optional Slide Spec handoff. It never creates
or claims to create a PPTX.

### `sp-deck`

Use for a new editable PPTX or a separate improved copy of an existing deck.
Low-level package editing, validation, and rendering use the suite-owned
`scripts/pptx_tool.py` facade and `shared/pptx_runtime/`. The plugin does not
load an external `document-skills` installation or distribute its copied code.
It deep-clones mutable slide dependencies, runs Open XML SDK markup/schema validation plus
suite-owned package/presentation semantics, and generates hidden-slide-aware paginated contact sheets.
Cleanup is transactional, inspection returns versioned slide metadata, and Linux rendering builds
the bundled AF_UNIX shim only when runtime detection proves the sandbox requires it.

### `sp-review`

Use for review, scoring, diagnosis, planned-vs-actual comparison, and concrete
slide fixes. Review is read-only by default. “Fix it directly” first produces a
diagnosis, then hands structured findings into the PPTX skill.

## Full PPTX Intake

Before production, confirm:

- topic;
- course/context and presentation type;
- audience and language;
- duration and slide count;
- individual/group format and members;
- rubric or required sections;
- source material and evidence boundaries;
- template, logo, or branding constraints;
- image-source strategy;
- visual style;
- required deliverables.

The plugin reuses confirmed information and asks only for missing fields. Each
missing field receives a recommendation and impact statement. Quality level
defaults to `high-score` and citation style to classroom citations — neither is
asked during intake. A user delegation such as “you decide” fills
recommendations but still requires approval of the complete Production Summary,
confirmed via `AskUserQuestion` (confirm / adjust / change style).

Production follows:

`intake_pending → intake_confirmed → planned → producing → qa → complete`

No environment, generation, rendering, or delivery command may run while the
state is `intake_pending`.

The suite records this gate with `workflow_guard.py` (init/confirm/transition).
While `intake_pending`, no environment, generation, rendering, or delivery
command may run. `ppt_pipeline.py` refuses illegal production steps. Narrow
PreToolUse hooks have separate responsibilities: `scripts/cost_guard.py` limits
plugin-source archaeology, same-hash image re-reads, repeated inspections, and
main-session image/context cost; `scripts/runtime_evidence.py` owns isolated
researcher/critic spawning and execution receipts; `scripts/production_entry_guard.py`
owns the stable production CLI surface and refuses direct internal build/evidence
bypasses; and `scripts/builder_guard.py` keeps per-page authoring source inside the
isolated presentation-builder. These runtime controls do not replace Production
Summary confirmation.

## Structured Handoff

Slide Spec YAML carries confirmed planning data into PPTX production. Its `meta`
supports topic, presentation type, audience, language, timing, ownership,
course, rubric, source material, template, image policy, visual style,
deliverables, and output prefix.

Existing-deck improvement additionally uses:

- `source_deck`
- `edit_intent`
- `review_findings`
- `preserve`
- `change_summary_required`

The original source deck is never overwritten.

Slide Spec v2 additionally carries scenario, audience depth, structure mode,
quality controls, layered slide copy/notes, Evidence Ledger references, locked
slides, and revision metadata. Legacy Slide Spec remains accepted.

When a Presentation Brief is supplied, every confirmed mirrored field must be
present and consistent in the Slide Spec; omission is a handoff error, not an
implicit default. Support-output generation may narrow, but never expand, the
confirmed deliverable set.

## Outputs

Deliverables are written under `${CLAUDE_PROJECT_DIR}/outputs`, or the current
project's `outputs/` directory when the environment variable is unavailable:

- `<topic>-presentation.pptx` (speaker notes live in the PPTX notes pane; the
  quality gate reads the delivered artifact, not the frozen spec field)
- `<topic>-speaker-notes.md`
- `<topic>-preview.png` or contact sheet
- `<topic>-presentation-package-report.json` from suite validation and reused
- `<topic>-delivery-report.json` with final gate evidence
- `<topic>-change-summary.md` for existing-deck improvements
- requested PDF, HTML teleprompter, training cards, references, quality report,
  and revision manifest

The plugin installation directory is read-only for user deliverables.

## Visual System

The PPTX skill first chooses one of three four-style categories, or `Other`, then loads one
lightweight reference from `visual-styles/`. Each formal style defines only its character, a light
six-role palette, the matching dark six-role palette for cover/section/closing pages, background
references, and one optional SVG reference. `Other` uses the same structure and must be shown in
the Production Summary before confirmation.

Light and dark are **one scheme, not two**: the dark companion shares the light palette's hue
family, so a deck never reads as a dark cover glued to unrelated light body pages. Both palettes
must clear the same contrast floors (text 4.5:1, accent 3:1 against canvas and surface).
`resolve_design_tokens()` guarantees a dark companion for every style and derives a
contrast-safe one for custom or legacy styles.

Styles are adaptive directions rather than fixed templates. Hard guardrails
protect readability, truthful evidence, source boundaries, and fit; layout
recipes, ratios, motifs, and normal density ranges remain adjustable to the
slide's narrative job. Typography-led pages are valid when no meaningful visual
is available, and filler icons, cards, or quotations are not acceptable.

The 12 styles do not control layout, shapes, image treatment, chart grammar, components, or page
rhythm. SVG motifs are optional and never inserted automatically; style references never override
capacity, evidence, contrast, or template rules.

Before final composition the deck resolves a 32-recipe
[`visual-reference-library.json`](skills/sp-deck/references/visual-reference-library.json) into
2–3 positive composition priors per slide, and high-leverage slides explore 2–3 genuinely
different silhouettes. Image search and generation are never assumed: declare providers in
`image-sources.json` (see
[`references/image-sourcing.md`](references/image-sourcing.md)) and the environment check reports
`image_search_ready` / `image_generation_ready` / `user_assets_ready`.

A reproducible
[golden sample](examples/golden-sample/README.md) exercises the whole pipeline and reaches
`status: complete`.

All styles share 36 page-layout inspirations in `layout-library.json` through
`pptx-layouts.js`. Suggestions map Slide Spec-native kind/visual values and filter by
assets, data, item counts, contraindications, declared capacity, and estimated
title-zone fit before scoring density and recent silhouettes. Missing
inputs follow explicit feasible fallback chains. `scripts/visual_system_smoke_gallery.py` produces
12x6 freeform style-reference galleries, a separate 36-layout reference/fallback gallery, and a
12-page SVG atlas, with optional rendering.

`deck.js` follows the official generation gotchas in
`skills/sp-deck/references/pptxgenjs-safety.md` and uses `pptx-helpers.js` for hard safety checks.
`pptx-composer.js`, `pptx-layouts.js`, `pptx-shapes.js`, `pptx-svg-library.js`, and
`pptx-visuals.js` are optional inspiration/toolbox/fallback modules. An unlocked Slide Spec
`layout` is advisory; `layout_lock: true` restores exact deterministic composition. The fallback
composer runs deck-wide preflight before rendering editable visual families
(hero, visual-dominant, process-path, timeline, comparison, dashboard,
architecture, matrix, quote, summary, reference) with shapes, connectors, labels,
contained images, accessible alt text, and projection-readable charts.

## Quality Gates

The default workflow has three gates: one Slide Spec/Brief validation report; package validation
plus complete rendering and page-by-page review of the final PPTX; then one simplified delivery
report binding the current PPTX, planning report, package report, previews, and requested outputs.
Separate content QA, asset, visual-inspection, and QA-manifest reports are advanced diagnostics,
not normal deliverables.

The v0.8 visual gates (Art Direction, composition candidates, exploration evidence) run in a single
pass, so a passing run prints one line instead of four JSON reports:

```powershell
python skills/sp-deck/scripts/run_gates.py --art-direction <a.yaml> --slide-spec <s.yaml> --evidence-dir <work-id> --lock-file <lock.json>
```

Full detail lands in `gates-report.json`, while the canonical delivery input
`visual-generation-report.json` is written alongside it automatically. Production sessions do
not invoke individual gate internals directly; production after intake is dispatched by
`skills/sp-deck/scripts/ppt_pipeline.py next --work-dir <wd> --json` (plan scaffolds
`deck.js` + `pages/pNN-*.js`; build refuses a monolithic generator). The working habits
that keep a run cheap — batching tool calls, in-place edits, write-once artifacts,
per-stage summaries, `sp-research` explicit spawn of `presentation-researcher`
instead of a generic researcher teammate,
DeepSeek vision reads in one parallel round (CD-9), and staying inside a 200k-shaped
window (CD-8) — are canonical in `references/cost-discipline.md`.
`scripts/session_cost.py` collapses usage-identical assistant rows within 2 seconds so
JSONL triple-counts do not inflate the report. Runtime hook ownership is deliberately
split: `scripts/cost_guard.py` handles context/inspection cost only;
`scripts/runtime_evidence.py` owns Agent isolation and execution receipts;
`scripts/production_entry_guard.py` owns direct production-entry integrity; and
`scripts/builder_guard.py` owns page-source isolation. This avoids duplicate policy
while still allowing the first legitimate image Read.

At most one repair loop may change the
spec/composer/generator and rebuild the complete candidate; a remaining QA blocker
is fixed via
`skills/sp-deck/scripts/ppt_pipeline.py repair --work-dir <wd>` instead
of resetting the whole pipeline. Deterministic misses are caught even earlier:
right after packing, `build` runs the `rendered` + `actual-content` gates plus the
quality gate's deterministic half (evidence closure, note timing, spec lock)
locally — they read the PPTX and the spec and need no critic; while they fail,
`render` is refused and `next` routes to a budget-free builder fix-and-rebuild —
the critic never reviews a doomed deck.

Calibration is reviewed by the independent `visual-critic`, not by the main
session. The main session authors the Slide Spec and the Art Direction, so it
cannot see that its own treatment repeats on every page; its own reading of the
preview PNGs is therefore not the review, and production `build` is refused until
`calibration/calibration-visual-review.json` exists, is bound to the current
calibration PPTX, carries no critical/major finding, and has a hook-owned
`calibration/calibration-critic-execution.json` proving that the critic read
every current calibration preview. The hook builds a scope-aware
`critic-preview-map.json` for either production or calibration and only permits
the critic to write that map's `review_output`; stale renders and wrong output
paths are rejected before review. An explicit calibration sample created with
`builder_packet.py --mode calibration --slides ...` is recorded atomically as
the active round, so `next` and `advance` preserve it instead of silently
restoring the default sample.
Calibration preview and the final rendered gate also inspect the PPTX itself and reject every
sRGB color outside the selected style's light/dark six-role palettes.

Each repair round spawns a **new** builder instance instead of continuing the
previous one: a builder instance that served several rounds reached 699K resident
context, and 96% of its cost was spent above 200K. `next --json` reports
`builder_instance_reuse` when one instance spans several rounds. If the builder
edited pages after the round's build, `build` allows one carry-over rebuild so
those edits reach the PPTX instead of consuming an extra round. The isolated
builder also never renders — `calibration_preview.py` and every render belong to
the main session, and `builder_guard.py` refuses both the render commands and the
inline-script forms of reading work-dir JSON or rewriting page modules.

Wall clock is turns × round-trip latency, and the gates are not what costs it:
the whole suite measured **150 seconds** across a 147-minute run (1.7%), against
**519 model round-trips** at one tool call each. When `next --json` supplies
`builder_shards`, the main session spawns ALL shards in one message so the page
work runs concurrently — shards are mutually exclusive by construction, each
writes its own `speaker-notes-shard-<N>.md` (build assembles sections by slide number and lets a
newer repair shard replace the older copy of that slide), and no gate
changes. `session_cost.py` reports `turns`, `tool_calls_per_turn` and
`turns_under_20min` so a run's time budget can be judged from data; its request
count now keeps one row per API call (by message id, max context) — the older
rule read a subagent as 480 requests where 261 were sent.

`repair_convergence` reports `suspect_gate_defect` when a blocker group is
byte-identical across two consecutive rounds while the rest of the list moved:
that group is not page work, so the run checks it once against the artifact and
either names a page-level fix or records it as a known gate limitation. Budget
extensions are refused while such a group accounts for most of the blocker list.

If a session is interrupted (the CLI is closed while a pipeline agent is still
running), reopen the project and run the same `ppt_pipeline.py next --work-dir
<wd> --json` dispatch: every step, including calibration (`calibration/`
manifest and render evidence), is derived from on-disk state, so the pipeline
points at the correct next step instead of re-running from scratch or
full-building with unresolved calibration blockers.

Results use `complete`, `incomplete`, or `blocked`. `complete` requires
`skills/sp-deck/scripts/ppt_pipeline.py complete --work-dir <wd>`.
The PptxGenJS wrapper
normalizes the generated package and atomically publishes it; layout/overflow quality
is caught by QA visual inspection and package validation.
Delivery reuses the package report instead of revalidating an unchanged deck.
Static XML findings alone are not proof of rendered clipping or readability.
CI also creates and renders a temporary scenario matrix for coursework, English
classroom, defense, competition, club showcase, research, software project,
data survey, and school-template editing; no generated deck or preview is
committed to the repository.

## Runtime

Claude Code does not automatically install this package's Python or Node runtime
dependencies. Use the repository-level installer or install manually:

```powershell
python -m pip install -r requirements.txt
python -m pip install -r requirements-claude-pptx.txt
npm ci
```

Useful checks:

```powershell
python scripts/check_claude_pptx_env.py --json --strict
python scripts/check_claude_pptx_env.py --mode edit_ooxml --json --strict
python scripts/pptx_tool.py --help
python scripts/validate_slide_spec.py path\to\spec.yaml --json
python scripts/validate_presentation_brief.py path\to\brief.yaml --json
python scripts/analyze_presentation_spec.py path\to\spec.yaml --json  # advisory analysis
python scripts/build_support_outputs.py path\to\spec.yaml --output-dir <project>\outputs --json
python scripts/create_revision_manifest.py old.yaml new.yaml --strict
python scripts/manage_versions.py snapshot --output-root <project>\outputs --revision-id r1 --file <deck>
python scripts/slide_spec_to_pptx_brief.py path\to\spec.yaml --output-dir <project>\outputs
python scripts/bump_version.py <version> --dry-run  # 统一版本升级
python scripts/session_cost.py --last 1  # session cost review (same as /sp-cost-report)
node scripts/run_with_pptxgenjs.js --probe
python scripts/smoke_pptx.py
```

## Environment Variables

The plugin relies on two environment variables automatically set by Claude Code:

| Variable | Set by | Purpose |
|----------|--------|---------|
| `${CLAUDE_PLUGIN_ROOT}` | Plugin system | Plugin installation directory; used for script references |
| `${CLAUDE_PROJECT_DIR}` | Runtime | Active project directory; used as the output root for deliverables |

User deliverables are always written under `${CLAUDE_PROJECT_DIR}/outputs`.
When `${CLAUDE_PROJECT_DIR}` is unavailable, the plugin falls back to the
current working directory.

No dotenv loader or `.env.example` is shipped. These variables are injected by
Claude Code; diagnose them through `sp-check-env` rather than copying a local env file.

## Package Boundary

This is a Claude Code package. It intentionally contains no `.codex-plugin`,
`agents/openai.yaml`, `artifact-tool`, or Codex runtime declaration.

### Open XML SDK Validation

The suite includes a small .NET adapter at
`shared/pptx_runtime/openxml_validator/` that wraps
`DocumentFormat.OpenXml` 3.5.1 for PPTX markup/schema validation. Build with:

```powershell
dotnet restore shared/pptx_runtime/openxml_validator/OpenXmlValidator.csproj
dotnet build shared/pptx_runtime/openxml_validator/OpenXmlValidator.csproj
```

This is a suite-owned implementation; no ECMA/ISO XSD files from the
`document-skills` upstream are copied or distributed. See
`references/pptx-runtime-provenance.md` for the full audit record.

See the repository [README](../../README.md) for install/update,
[AGENTS.md](../../AGENTS.md) for validation and release, and
[CHANGELOG.md](../../CHANGELOG.md) for version history.

Per-work state lives in `outputs/.pptx-work/<work-id>/workflow-state.json`
(`--work-id` on init/confirm). Modes: `create`, `edit_ooxml`,
`rebuild_from_source` (needs `source-analysis.md`). Edits keep the source file
and require `change-summary.md`. Isolated `visual-critic` / researcher receipts
are required before QA/complete where those stages apply. Image provider
commands need a user-approved SHA256; project JSON cannot authorize them.
PowerPoint COM checks are separate: `references/powerpoint-smoke.md`. LibreOffice
success is not Office certification.
