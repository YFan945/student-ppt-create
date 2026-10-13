# Student Presentation Suite

A Claude Code plugin for student academic presentations: evidence gathering, outlines, editable PPTX production, and read-only review.

Install, update, migration and uninstall instructions belong to the [marketplace README](../../README.md). Runtime dependencies belong to this plugin; no external document-skills or Codex runtime is required.

Design references are optional tools. Typography, chart/icon counts, color usage, background rhythm and composition follow the content and rendered pages; no legacy numeric design rules are included in current authoring guidance.

New page source receives colors, font families and author-provided typography. The scaffold injects no layout rules, font floors, column limits, title/footer zones or background recipes. Every design_freedom value permits free page functions; the runtime never selects a layout or paints a background automatically. Useful explanations and evidence remain on slides.

Audience-facing language follows the required shared standards; tables use editable themed headers, banding and meaningful emphasis.

Automatic monetary, token, request-count, research-time and repair-round budgets have been removed. Usage reports remain observational; real errors and incomplete work still require repair.

## Four skills

| Skill | Outcome |
| --- | --- |
| `sp-research` | A Research Pack with traceable external evidence; one isolated researcher when retrieval is needed |
| `sp-outline` | A structured outline, Slide Spec and speaking plan |
| `sp-deck` | Editable PPTX creation or improvement, authored in the main conversation |
| `sp-review` | Read-only diagnosis of an existing deck; editing requires a separate edit request |

Activation requires a student-owned academic context and an explicit presentation-related request. Review preserves the original file.

## Production

The main conversation reads the actual assets, chooses compositions, writes page modules, inspects rendered pages, and fixes them in the same context. There are no Builder/critic subagents, calibration stages, packets, shards or execution receipts for deck production.

New work defaults to `design_freedom: auto`: free coordinates and shared drawing helpers. `guided` and `deterministic` remain optional tools. `quality_level` describes the desired care; it does not add agent stages or impose templates.

Images, editable charts and diagrams should explain the content. There are no fixed image quotas, global font floors, required color ratios or gallery imitation. User-specified branding, templates, logos and preserved content remain binding. Art Direction is optional.

Slide Spec 2.1 freezes core meaning, exact facts, numbers and sources while allowing presentation wording to change. Actual copy is captured from the final artifact. Meaning and visual quality are checked by the author in the main conversation; this is **self-check, not independent semantic review**. Old 1.0/2.0 copy matching remains supported.

The tools batch build, font processing, exact-content readback, package validation and rendering. They return concrete problems and current previews. The author looks at those previews before exporting. Production uses `plan → run → complete`; commands and runnable authoring examples are in [main-session-production.md](skills/sp-deck/references/main-session-production.md).

## Assets, typography and editing

New student decks aim for substantive content, varied visual expression and layered color. Typography, density and compositions follow the content and full-size renders; word/character caps apply only when explicitly confirmed. With no external images, editable diagrams, tables, charts and semantic icons remain available. See the [runnable visual examples](skills/sp-deck/references/main-session-visual-examples.md).

Before delivery, inspect every full-size rendered page and compare supplied references, repair and render again, then scan the whole deck. `run` reports technical checks, geometry risks and pending author review tasks; `ok` does not certify aesthetics or completion of visual/semantic self-check. The commands remain `plan → run → complete`.

New tasks do not impose diagram item quotas or a supporting-point cap. Explicit word/character limits accept positive integers. Custom styles may add semantic category colors and omit unused backgrounds/SVG motifs. Text overlap uses measured line regions when available, with conservative box checks for unmeasured content.

- Use real supplied assets first. Preserve their aspect ratios and evidence regions, record sources and permissions, and do not invent comparison data.
- Shared fontkit measurement supports Chinese line breaking and rich-text emphasis. Final rendering still determines actual readability.
- Page modules use shared helpers or native pptxgenjs objects; the harness records geometry, backgrounds, notes and actual copy.
- Font choices and sizes belong to the author. Page typography aliases are mapped explicitly, and unknown keys produce an actionable error.
- OOXML editing preserves the source deck; rebuilt decks remain editable. Changes are accompanied by a change summary.
- Speaker notes and support scripts come from the final PPTX notes panes. Only confirmed deliverable types are exported.

## Work files and recovery

Artifacts belong to the active project's `outputs/`; temporary sources and previews belong to `outputs/.pptx-work/<work-id>/`. Never generate inside the installed plugin or marketplace repository.

The existing intake confirmation is retained. Deterministic status and artifact bindings are maintained by tools, not copied by the model. Continue repairing actual issues until the task is complete; no default repair-round budget stops production.

Historical manifests remain readable through `status`. They are not silently migrated or resumed through the removed agent pipeline. Continue an old artifact as a new edit task while keeping the original.

## References

- [Model-led design](references/model-led-design.md)
- [Main-session production](skills/sp-deck/references/main-session-production.md)
- [Image sourcing](references/image-sourcing.md)
- [Research workflow](references/research-workflow.md)
- [Development and validation](AGENTS.md)
