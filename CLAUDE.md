# Claude Code session notes

This file is loaded automatically in Claude Code. **Do not copy architecture,
commands, or policy here.** Those go stale. Canonical rules:

| File | When to open it |
| --- | --- |
| [`AGENTS.md`](AGENTS.md) | Marketplace repo: `main` is the only publishable source, layout, validation, release, **and which docs to update together** |
| [`plugins/student-presentation-suite/AGENTS.md`](plugins/student-presentation-suite/AGENTS.md) | Plugin internals: skills, state machine, local test commands |

If this file and `AGENTS.md` disagree, **`AGENTS.md` wins**. Fix this file; do
not layer a third copy of the rules.

## Do not reintroduce

- Publishing or installing from `YFan945/Personal-Student` / `claude-code`
- Codex plugin files (`.codex-plugin`, `agents/openai.yaml`, `artifact-tool`)
- Writing deliverables into `plugins/` or the plugin install directory
- Duplicating README sections across marketplace and plugin copies

## Doc sync (mandatory)

When you change behavior, install, architecture, requirements, or release
steps, follow the matrix in `AGENTS.md` → **Documentation Ownership**. English
and Chinese README pairs update together. Do not paste the same paragraph into
four READMEs.
