# Student Presentation Suite for Claude Code

[中文](README-zh.md) | English

**This file (marketplace README):** how to install, verify, update, and
uninstall the plugin from GitHub, plus short usage examples and troubleshooting.
It does **not** own skill contracts, visual rules, or CLI flags — those live in
[`plugins/student-presentation-suite/README.md`](plugins/student-presentation-suite/README.md).
When editing docs, follow [AGENTS.md](AGENTS.md) → Documentation Ownership.

> This repository is the Claude Code-only marketplace for
> `student-presentation-suite`. **Download and install it from the `main`
> branch of this repository** — see Download And Install below. Installation,
> dependencies, and runtime are Claude Code specific; do not install it in
> **OpenAI Codex**.

`student-presentation-suite` supports student-owned university presentations,
including coursework reports, thesis defenses, and group presentations. In
Claude Code it can research evidence, plan an outline and speaker notes, create
an editable PPTX, review an existing deck, or produce a separate improved copy.

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
| Gather and grade evidence | `sp-research` | Research Pack only; no PPTX |
| Outline, notes, or group allocation | `sp-outline` | Markdown planning documents; no PPTX |
| Create, rebuild, or edit an editable PPT/PPTX | `sp-deck` | PPTX, speaker notes, and preview |
| Review, score, or diagnose an existing deck | `sp-review` | Read-only review by default |

Pipeline, intake, visual system, and quality gates:
[plugin README](plugins/student-presentation-suite/README.md).
PPTX creation uses suite-owned `pptx_tool.py` and `shared/pptx_runtime/` (no
external `document-skills`). Web editing and cloud sync are not claimed.

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

### Recommended: Add The GitHub Marketplace (No Clone Needed)

Claude Code marketplaces can point straight at a GitHub repository, so there is
nothing to clone first. Run two commands:

```powershell
claude plugin marketplace add YFan945/student-ppt-create@main
claude plugin install student-presentation-suite@claude-personal
```

Restart Claude Code (or run `/reload-plugins`) afterwards.

The plugin also needs Python and Node.js dependencies. Use the installer to add
them in one go — it installs into the plugin copy Claude Code actually loads:

```powershell
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/YFan945/student-ppt-create/main/scripts/install_claude_plugin.ps1" `
  -OutFile "$env:TEMP\install_claude_plugin.ps1"
Set-ExecutionPolicy -Scope Process Bypass
& "$env:TEMP\install_claude_plugin.ps1" -Migrate
```

`-Migrate` removes the obsolete `student-presentation-suite@personal`
registration and cache, then:

1. verifies .NET 8 and installs Python and Node.js dependencies;
2. registers the `claude-personal` marketplace from GitHub, pinned to `main`;
3. installs and enables `student-presentation-suite@claude-personal`;
4. runs the strict environment check and displays plugin status.

Update later with `claude plugin marketplace update claude-personal`.

The installer never downloads a .NET SDK implicitly. If .NET 8 is absent, either install it
yourself or explicitly opt in to the pinned 8.0.423 user-local download (about 285 MB):

```powershell
& "$env:TEMP\install_claude_plugin.ps1" -InstallDotNetSdk
```

### Local Checkout (Development Or Offline)

Clone `main` and register that directory with `-Local`:

```powershell
git clone --branch main --single-branch `
  https://github.com/YFan945/student-ppt-create.git `
  "$env:USERPROFILE\.agents\claude-plugins"

Set-Location "$env:USERPROFILE\.agents\claude-plugins"
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\install_claude_plugin.ps1 -Local -Migrate
```

Already cloned? Pull, then reinstall:

```powershell
Set-Location "$env:USERPROFILE\.agents\claude-plugins"
git switch main
git pull --ff-only origin main
.\scripts\install_claude_plugin.ps1 -Local
```

To re-register without reinstalling dependencies, or to register an existing
working copy such as `E:\student-ppt-create`:

```powershell
.\scripts\install_claude_plugin.ps1 -Local -SkipDependencies -SkipMarketplaceClone
.\scripts\install_claude_plugin.ps1 -Local -InstallRoot "E:\student-ppt-create" -SkipMarketplaceClone
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

Production is gated by a confirmed Production Summary (`workflow_guard.py` /
`ppt_pipeline.py`). Cost and spawn guards are documented in the
[plugin README](plugins/student-presentation-suite/README.md).

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
result, and status: `complete`, `incomplete`, or `blocked`. Visual system, QA
DAG, and CI render matrix: [plugin README](plugins/student-presentation-suite/README.md).

## Update And Uninstall

Update the repository and plugin:

```powershell
Set-Location "$env:USERPROFILE\.agents\claude-plugins"
git switch main
git pull --ff-only origin main
claude plugin update -s user student-presentation-suite@claude-personal
```

GitHub-marketplace installs: `claude plugin marketplace update claude-personal`.

Uninstall:

```powershell
claude plugin uninstall student-presentation-suite@claude-personal
claude plugin marketplace remove claude-personal
```

## Troubleshooting

### The Plugin Does Not Trigger

Make the student academic context and presentation intent explicit. You can
also name `sp-research`, `sp-outline`, `sp-deck`, or `sp-review`
directly in the request.

### The Environment Check Fails

Run:

```powershell
python .\plugins\student-presentation-suite\scripts\check_claude_pptx_env.py --json --strict
python .\scripts\check_installed_version.py --json
```

Install the missing Python or Node.js dependency reported by
the check. LibreOffice and Poppler are required for rendered QA and `complete`
delivery; candidate PPTX generation can run without them.

### Workflow State Is Stuck

If QA found a blocker, do **not** reset: repair through the pipeline rework edge
to rebuild the generator and re-enter QA:

```powershell
python .\plugins\student-presentation-suite\skills\sp-deck\scripts\ppt_pipeline.py repair --work-dir <wd>
```

After QA passes, complete with:

```powershell
python .\plugins\student-presentation-suite\skills\sp-deck\scripts\ppt_pipeline.py complete --work-dir <wd>
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

### Can Codex Use This Repository?

No. This repository supports Claude Code only.

## Development And Releases

Validation commands, version bumps, and GitHub Release steps:
[AGENTS.md](AGENTS.md). Contributor setup: [CONTRIBUTING.md](CONTRIBUTING.md).
Publish only from this repository's **`main`** branch.

## License

MIT. See [LICENSE](LICENSE).
