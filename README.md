# Student Presentation Suite for Claude Code

[中文](README-zh.md) | English

> This branch is built specifically for **Claude Code**. Its installation,
> dependencies, and runtime behavior are not intended for Codex. If you use
> **OpenAI Codex**, see the
> [`main` branch](https://github.com/YFan945/Personal-Student/tree/main)
> instead.

`student-presentation-suite` supports student-owned university presentations,
including coursework reports, thesis defenses, and group presentations. In
Claude Code it can plan an outline and speaker notes, create an editable PPTX,
review an existing deck, or produce a separate improved version.

Its visual runtime includes 12 lightweight style references in three categories — each with a
light palette plus the matching dark scheme for cover, section and closing pages — an `Other`
custom entry, a 32-recipe visual composition reference library, 36 shared composition
references, an original SVG/non-rectangular shape toolbox, a safety/fallback composer,
and content/file/visual QA evidence bound to the final PPTX hash. Image search and
generation are declared explicitly through `image-sources.json` and reported as
`image_search_ready` / `image_generation_ready`, so planning never promises a
capability the session does not have.

A reproducible
[golden sample](plugins/student-presentation-suite/examples/golden-sample/README.md)
runs the full v0.8 pipeline end-to-end and reaches `status: complete`.

Plugin install ID:

```text
student-presentation-suite@claude-personal
```

The suite owns its PPTX runtime end-to-end; ownership and audit provenance are
documented in
[`plugins/student-presentation-suite/references/pptx-runtime-provenance.md`](plugins/student-presentation-suite/references/pptx-runtime-provenance.md).

## Features

| Request | Skill | Result |
| --- | --- | --- |
| Outline, slide content, notes, or group allocation | `student-presentation` | Markdown planning documents; no PPTX |
| Create, rebuild, or edit an editable PPT/PPTX | `student-presentation-ppt` | PPTX, speaker notes, and preview |
| Review, score, or diagnose an existing deck | `student-presentation-review` | Read-only review by default |

PPTX creation and editing use the suite-owned `pptx_tool.py` facade and
`shared/pptx_runtime/` implementation. No external `document-skills` plugin,
cache path, or copied upstream runtime is required or distributed.
The runtime selectively deep-clones mutable slide dependencies, runs Open XML SDK markup/schema
validation plus suite-owned OPC semantics, and produces hidden-slide-aware paginated contact sheets.
Orphan cleanup is transactional, slide inspection exposes versioned per-page metadata, and Linux
rendering can build a suite-owned AF_UNIX compatibility shim only when sandbox detection requires it.

## Structured Workflow And Controls

Version 0.4 adds a confirmed Presentation Brief before Slide Spec/PPTX work:

- automatic classification for coursework, defense, competition, club showcase, and research;
- audience type and explanation depth;
- problem-solution, research, timeline, comparison, case-study, and product structures;
- beginner/expert interaction and basic/high-score quality modes;
- per-slide text limits, visual/text ratio, notes, key lines, citation style, exports, and versioning;
- layered generation: directory → slide claims → PPT copy → speaker version → Slide Spec;
- Evidence Ledger, deterministic quality report, locked slides, revision manifests, training cards, and rehearsal support.

Local exports can include PPTX, PDF, previews, Markdown notes, HTML teleprompter,
quality report, references, and revision manifest. Web editing and cloud
synchronization require an external service and are not claimed by this plugin.

## Requirements

Install these tools first:

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- Git
- Python 3.10+
- Node.js and npm
- .NET 8 SDK (required for Open XML validation)
- LibreOffice and Poppler (required for rendered QA and `complete` delivery; candidate PPTX generation can run without them)

Check the basic commands:

```powershell
claude --version
git --version
python --version
node --version
npm --version
```

## Download And Install

### Recommended Windows Installation

Run in PowerShell:

```powershell
git clone --branch claude-code --single-branch `
  https://github.com/YFan945/Personal-Student.git `
  "$env:USERPROFILE\.agents\claude-plugins"

Set-Location "$env:USERPROFILE\.agents\claude-plugins"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_claude_plugin.ps1 -Migrate
```

`-Migrate` removes the obsolete `student-presentation-suite@personal`
registration and cache, then:

1. verifies .NET 8 and installs Python and Node.js dependencies;
2. registers the local `claude-personal` marketplace;
3. installs and enables `student-presentation-suite@claude-personal`;
4. runs the strict environment check and displays plugin status.

Restart Claude Code after installation.

The installer never downloads a .NET SDK implicitly. If .NET 8 is absent, either install it
yourself or explicitly opt in to the pinned 8.0.423 user-local download (about 285 MB):

```powershell
.\scripts\install_claude_plugin.ps1 -Migrate -InstallDotNetSdk
```

### Existing Checkout

```powershell
Set-Location "$env:USERPROFILE\.agents\claude-plugins"
git switch claude-code
git pull --ff-only origin claude-code
.\scripts\install_claude_plugin.ps1
```

To re-register the plugin without reinstalling dependencies:

```powershell
.\scripts\install_claude_plugin.ps1 -SkipDependencies -SkipMarketplaceClone
```

## Verify The Installation

```powershell
claude plugin marketplace list
claude plugin list
claude plugin details student-presentation-suite@claude-personal
python .\plugins\student-presentation-suite\scripts\check_claude_pptx_env.py --mode create --json --strict
python .\plugins\student-presentation-suite\scripts\pptx_tool.py --help
```

The results should include:

- marketplace: `claude-personal`
- plugin: `student-presentation-suite@claude-personal`

If Claude Code does not discover the plugin immediately after installation or
update, exit Claude Code completely and start it again.

## Usage

Open Claude Code from your coursework project:

```powershell
Set-Location D:\my-course-project
claude
```

Describe the task in natural language. The plugin is intentionally limited to
clear student academic presentation contexts; generic business or marketing
decks do not route into these skills.

Before creating or editing a PPTX, Claude prepares a complete
`Production Summary` covering the topic, course, audience, language, duration,
slide count, rubric, sources, visual style, and deliverables. Production starts
only after you confirm it.

The suite records this boundary through `workflow_guard.py` state commands
(init/confirm/transition); the approved summary hash and workflow state are
stored in the project output directory. State is enforced by SKILL text
self-discipline — the PreToolUse hook is removed, so no command is intercepted
automatically.

Deliverables are written to the active project's `outputs/` directory, never
to the plugin installation. Existing source decks are never overwritten.

## Examples

### 1. Outline And Speaker Notes Only

```text
I am a software engineering student preparing a six-minute course report on
"AI-assisted software testing." Design an eight-slide outline with speaker
notes and timing for each slide. Do not create a PPTX.
```

This produces an outline, slide-level notes, transitions, and optional Q&A.

### 2. Create An Editable PPTX

```text
Create an editable PPTX for my university course.
Topic: "Reflections on Learning Generative AI." Chinese, individual report,
five minutes, eight slides, for my instructor and classmates. Use a clean,
modern style and deliver the PPTX, slide-level notes, and a preview.
```

Claude fills any missing requirements, shows the complete
`Production Summary`, and waits for confirmation before production.

### 3. Group Course Presentation

```text
Our four-person team has a 12-minute database course presentation on
"Consistency in Distributed Databases." Create a 12-slide English PPTX,
assign slides and speaking time to each member, and include speaker notes and
likely instructor questions.
```

The plugin handles ownership, handoffs, timing, and Q&A preparation.

### 4. Thesis Defense

```text
Use the thesis, experiment results, and images in this project to create a
15-slide Chinese PPTX for my undergraduate thesis defense. Keep it within ten
minutes and emphasize the research question, method, results, contributions,
and limitations. Use only my supplied evidence and do not invent data.
```

Place the thesis, data, images, and university template in the project before
starting Claude Code.

### 5. Review An Existing Deck Without Editing

```text
Review outputs\defense.pptx for structure, text density, font size, chart
readability, timing, and defense risks. Report concrete fixes only; do not
modify the source file.
```

The report identifies the target slide, issue, impact, severity, and fix.

### 6. Review And Produce An Improved Copy

```text
Review outputs\course-report.pptx and then create an improved copy.
Preserve the university template, logo, approved data, and citations. Improve
the narrative, layout, and speaker notes, do not overwrite the original, and
provide a change summary.
```

The plugin diagnoses the deck first, confirms the editing requirements, then
creates a separate PPTX and change summary.

## Output Files

Depending on the request, `outputs/` may contain:

```text
<topic>-outline.md
<topic>-presentation.pptx
<topic>-speaker-notes.md
<topic>-preview.png
<topic>-presentation-package-report.json
<topic>-actual-content-report.json
<topic>-visual-review.json
<topic>-quality-report.json
<topic>-delivery-report.json
<topic>-change-summary.md
<topic>-presentation.pdf
<topic>-teleprompter.html
<topic>-training-cards.md
<topic>-revision-manifest.json
```

The final response reports each absolute file path, slide count, rendered QA
result, and the status: `complete`, `incomplete`, or `blocked`. v0.7.1 uses four quality stages:
(1) validate and freeze the Slide Spec; (2) run the Actual Element Registry, package validation,
and PPTX artifact readback against that frozen plan; (3) render every page, write a structured
visual review, and run visual-score, deck-rhythm, evidence-closure, and speaker-timing gates;
(4) bind those reports to the current PPTX, Slide Spec, and spec-lock hashes in the delivery report.
Legacy content/asset/QA manifests remain optional advanced diagnostics.
`deck.js` remains adaptive-freeform PptxGenJS: the model chooses expression, focal point, and
composition language, while the Actual Element Registry enforces real-element geometry/text-fit
baselines. Suite-owned layout, visual, shape, SVG, and composer libraries remain inspiration or
deterministic fallback. Render QA no longer treats “no overflow/overlap” as sufficient design
quality: high-score decks also evaluate hierarchy, focal point, composition, visual interest,
whitespace, AI-template feel, and repeated structures across the deck.
Eleven editable visual families (`pptx-visuals.js`) provide hero,
visual-dominant, process-path, timeline, comparison, dashboard, architecture,
matrix, quote, summary, and reference structures without post-generation patch
loops. The 12 formal styles resolve only to character, six color roles, four background references,
and one optional SVG reference; `Other` uses the same confirmed structure. They share 36
page-layout inspirations ranked by content feasibility, title-zone capacity, density, and silhouette history—never by visual style. Slide Spec `layout`
is an adaptable hint unless `layout_lock: true`; missing assets follow explicit feasible fallbacks. Recipes are adaptive defaults rather
than per-slide templates: narrative fit, readability, and source safety take
priority. A unified smoke tool builds six-page galleries for all 12 styles, a
separate reference/fallback gallery for all 36 layouts, and a 12-page SVG atlas.
Brief-to-Slide Spec handoff treats missing mirrored confirmed fields as errors,
and support outputs may only narrow the confirmed deliverable set. When
MarkItDown is unavailable, suite-owned OOXML extraction still checks complete
slide, speaker-note, and chart text.
The release workflow also renders a temporary scenario matrix on Linux for
coursework, English-classroom, defense, competition, club-showcase, research,
software projects, data surveys, and school-template editing.

## Update And Uninstall

Update the repository and plugin:

```powershell
Set-Location "$env:USERPROFILE\.agents\claude-plugins"
git pull --ff-only origin claude-code
claude plugin update -s user student-presentation-suite@claude-personal
```

Uninstall:

```powershell
claude plugin uninstall student-presentation-suite@claude-personal
claude plugin marketplace remove claude-personal
```

## Troubleshooting

### The Plugin Does Not Trigger

Make the student academic context and presentation intent explicit. You can
also name `student-presentation`, `student-presentation-ppt`, or
`student-presentation-review` directly in the request.

### The Environment Check Fails

Run:

```powershell
python .\plugins\student-presentation-suite\scripts\check_claude_pptx_env.py --json --strict
python .\scripts\check_installed_version.py --json
```

Install the missing Python or Node.js dependency reported by
the check. LibreOffice and Poppler are recommended but not required — missing
them skips rendered QA and PDF export but does not block PPTX generation.

### Workflow State Is Stuck

If QA found a blocker, do **not** reset: return to production via the rework edge
to rebuild the generator and re-enter QA:

```powershell
python .\plugins\student-presentation-suite\scripts\workflow_guard.py transition --to producing --reason "<blocker summary>"
```

`reset` / `unblock` are last resorts only — they drop the confirmed summary and
force a full restart. To recover from `blocked` state after fixing a missing
dependency:

```powershell
python .\plugins\student-presentation-suite\scripts\workflow_guard.py unblock
```

`unblock` returns the project to `intake_pending`; confirm the Production Summary
again before resuming production.

### Where Are Generated Files?

They are under the project directory from which Claude Code was started:
`outputs/`. If `CLAUDE_PROJECT_DIR` is set, the location is
`${CLAUDE_PROJECT_DIR}/outputs`.

### Can Codex Use This Branch?

No. This branch supports Claude Code only. Use the
[`main` branch](https://github.com/YFan945/Personal-Student/tree/main)
for Codex.

## Development And Releases

Starting with 0.4.1 the project also includes a dedicated engineering toolchain:

- **Python linting**: Ruff with selected rule sets (E, F, W, I, N, UP, B, SIM, ARG, RET)
- **JavaScript linting**: ESLint with standard rules + Prettier formatting
- **Cross-editor**: `.editorconfig` for consistent indentation and line endings
- **Security scanning**: `pip-audit` and `npm audit` in CI pipeline
- **Dependency management**: Dependabot configured for pip, npm, and GitHub Actions
- **Integration tests**: End-to-end smoke tests for the spec → bridge pipeline
- **Test utility extraction**: Shared [`test_helpers.load_module()`](plugins/student-presentation-suite/tests/test_helpers.py) eliminates 7 duplicate module loaders
- **Community standards**: Issue/PR templates, `CONTRIBUTING.md`, `SECURITY.md`

See [AGENTS.md](AGENTS.md) and [CHANGELOG.md](CHANGELOG.md) for source
validation and release rules. Claude Code changes are published only from
`claude-code`, never from `main`.

## License

MIT. See [LICENSE](LICENSE).
