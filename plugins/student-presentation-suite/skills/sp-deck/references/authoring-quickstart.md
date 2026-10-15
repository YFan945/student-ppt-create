# Main-session authoring quickstart

Read this once for new model-led pages. Use the full helper API only for a specific operation; do not study runtime/validator internals before writing pages.

This is the supported normal-create contract. Start page implementation from it; before the first build, do not inspect runtime/registry/text-measurement/exact-match source or dump the whole API/schema. Use one filtered helper entry when an operation is genuinely unclear. Concrete build errors justify targeted implementation inspection only when this contract and that entry cannot resolve them. Native backgrounds/panels are registered in paint order; later readable foreground text may sit on them. Warnings are inspection signals, not a reason to reverse-engineer the registry before drawing.

## Approved intake and paths

Use the current skill base directory; root policies are ../../references, not this local references directory. The plugin root is the skill base's ../.. . Do not rediscover installed versions/cache folders after the skill has loaded. For a new work-id, write the complete summary and obtain its approval, then:

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" init --work-id <work-id> --topic <topic>
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" confirm --work-id <work-id> --summary-file <approved-summary.md>
python "${CLAUDE_PLUGIN_ROOT}/scripts/check_claude_pptx_env.py" --mode create --json --strict
```

The shell runs in the active project; confirmed work lives in outputs/.pptx-work/<work-id>. Only initialize a new id; continue existing production using its current state. Missing material belongs in the same clarification round before the final summary. Resolve output/imagery permissions from actual authorization, not historical pasted messages.

## Minimal planning input

After the approved summary, create the 2.1 Slide Spec in the work directory and call `plan`. This valid single-page shape shows normal fields; replace the example content, facts, number of pages and speaking times from the task. Use the current validator for errors rather than querying the full schema repeatedly.

```json
{
  "schema_version": "2.1", "research_scope": "C",
  "meta": {"topic": "实验结果", "language": "Chinese", "slide_count": 1,
    "duration_min": 1, "quality_level": "fast", "citation_style": "none",
    "include_speaker_notes": true, "design_freedom": "auto",
    "deliverables": ["pptx", "preview"], "output_dir": "outputs/experiment"},
  "slides": [{"id": 1, "title": "实验结果", "content": ["合成实验的样本量为233"],
    "timing_sec": 60, "owner": "Individual",
    "semantic_requirements": {"must_convey": [{"id": "sample", "text": "合成实验的样本量为233"}],
      "must_show_exact": ["233"]}}]
}
```

`must_convey` freezes meaning; `must_show_exact` freezes required words/numbers. Only freeze literal wording when requested. A `visual` object may carry `type`, `purpose` and `details`; it describes what to communicate, not a mandatory geometry. For evidence/research, existing-deck edits or custom style fields, load the relevant contract only then. `meta.output_prefix` is optional; delivery defaults to `outputs/<work-id>` when output_dir is absent. Confirm materials and image permissions before production, preserving the normal intake gate.

## Page contract

`ctx` contains `slide`, `pptx`, `H`, `tokens`, `n`, and `registry`. The page owns the full canvas. `tokens.palette` and font families are starting choices, not a prescribed composition. Use `ctx.H.SLIDE_W_IN` / `SLIDE_H_IN` for its actual dimensions.

```javascript
module.exports = function ({ slide, H, tokens }) {
  slide.background = { color: tokens.palette.canvas };
  H.addFittedText(slide, [
    { text: '科研信息汇总：' },
    { text: '找到可参与的方向', options: { bold: true, color: tokens.palette.primary_accent } },
  ], { x: .6, y: 1, w: 8, h: 1 }, tokens, 'chinese', 'body', { fontSize: 22, margin: 0 });
};
module.exports.presentation_copy = { headline: '科研信息汇总', visual_labels: ['找到可参与的方向'] };
module.exports.notes = '先讲信息入口，再说明后续行动。';
```

The coordinates, size and synthetic wording above illustrate the API, not a page recipe. Replace them from your own material. `presentation_copy` names actual visible wording; purpose descriptions are not labels. Notes speak selectively and preserve factual boundaries.

## Text and emphasis

`H.addFittedText(slide, value, box, tokens, 'chinese', role, options)` accepts plain text or an array of `{text, options}`. Supply the size you choose; measured pages do not automatically shrink it. `options` supports fontFace, cjkFontFace, fontSize, color, bold, align and margin. Per-run bold/color retains editable inline emphasis. Roles identify content, not title/footer zones.

An overflow means the region is insufficient: improve wording/grouping or geometry without dropping required support. `H.fitText(value, box, H.rolePolicy(tokens, 'chinese', role, options))` returns `fits`, `requiredH`, `lines` and `lineGeometry` without drawing. Ordinary Chinese quotation marks use the Chinese family; explicit run font choices remain binding. Use `addPositionedText` only when a real render needs controlled mixed-language placement. Never claim PowerPoint behavior from LibreOffice alone.

## Images, diagrams and tables

- `H.addPlannedImage(slide, {path, width, height}, box, pptx)` needs an inspected file and its real pixel dimensions. Default placement preserves evidence; crop deliberately and retain protected regions. Use the asset manifest for provenance and approved placeholders.
- Native `slide.addShape('rect'/'ellipse'/'line', options)` draws editable relationships. `decorative:true, bleed:true` permits an intentionally clipped background shape; it does not permit text/evidence outside the canvas or hiding foreground information.
- For native lines, keep width/height non-negative; use the minimum endpoint coordinates, absolute extents and flipH/flipV for reversed diagonals. Negative extents can produce invalid DrawingML even when the line looks plausible in a render.
- Native `slide.addTable(rows, {x,y,w,h,colW,rowH,fontSize,...})` uses explicit editable cell geometry. Each row is an array; rich cells are `{text, options}`. Provide all column widths and row heights when unequal; merged cells need explicit shapes/text. Do not invent data to fill a table.
- A flow is nodes + truthful labels + connectors; a comparison is aligned dimensions and supported values. A panel should contain explanation/evidence, not only a large name. See runnable visual examples only for the expression the current material needs.

## Production and inspection

`plan` creates the page functions; `run` builds/checks/renders and returns `check_summary`, `changed_pages`, previews and full-report paths. Read current reports with `status`, not another `run`. Keep JSON stdout separate from logs; save to a real project path rather than a shell-specific `/tmp` name.

Inspect all pages on the first run. After changes, inspect every affected final page in full and the latest contact sheet; `changed_pages` assists this, including shared source changes. Then `complete` exports selected deliverables to the planned `output_dir` (default `outputs/<work-id>`), including all slide PNGs when preview is selected. Leave frozen inputs and exported files at their bound paths. `status` detects moved/modified delivery files without rebuilding.

For one helper, use `node "${CLAUDE_PLUGIN_ROOT}/scripts/pptx-helpers.js" --describe --function addFittedText`. It returns its actual signature, behavior and example. Only inspect a specific implementation after the supported usage cannot resolve a concrete issue.

Implemented page functions may retain a provenance comment; empty functions remain unfinished, and runtime checks require real drawn objects. Mixed-size inline number/unit fragments align to measured font baselines, retaining their logical text group and accurate geometry. Do not manually guess a unit offset to compensate for the runtime.

## Relationships, numeric facts and visual safety

For an optional relationship helper, require `${CLAUDE_PLUGIN_ROOT}/scripts/pptx-relations.js`. Supply actual supported content, box and fontSize; there is no global size or layout recipe:

- `metric(ctx, {label,value,unit,context?}, box, {fontSize,labelSize?,color?})`: editable rich text in one object, suitable for the fact_bindings contract in slide-spec.md. The numeric value is a string; label and unit retain their actual meaning.
- `evidenceRows(ctx, [{label,detail}], box, {fontSize,labelWidth?,gap?,rowGap?})`: nearby explanation with a shared reading axis.
- `processSteps(ctx, [{title,rows:[{label,detail}]}], box, {fontSize,titleHeight?,labelWidth?,gap?,rowGap?})`: directional process with explicit inputs/actions/retained evidence; rowGap and horizontal gap are independent.
- `annotatedImage(ctx, asset, [{x,y}], box, {markerFontSize,markerSize?,color?})`: numbered anchors in normalized coordinates on an inspected image. Box must match asset aspect ratio; place markers away from evidence text and explain them nearby. It cannot determine whether a marker hides image content.

`decorative` and `bleed` allow intended background treatment, not opaque foreground masks over text. Known solid foreground/background contrast below 3:1 is an error; 3–4.5:1 requests size/weight/viewing review. Images, gradients, transparency, unknown colors and partial surfaces remain explicitly unresolved; check their final renders. No global font floor is introduced. Complete same-material examples and their limitations are in main-session-visual-examples.md.
