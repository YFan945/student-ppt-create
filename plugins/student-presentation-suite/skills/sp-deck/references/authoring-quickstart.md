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

## Design before drawing

Use the existing handoff plan for this page’s question/answer, visible supporting groups, main subject and speaking order. Choose rich coordinated colors and intentional text hierarchy; role defaults distinguish title/body/caption but remain fully overridable. Read `../../../references/template-workflow.md`: default search uses the shipped reference library; user templates take priority. Inspect candidate previews and selected-page recipes, then reconstruct editable objects with actual task content. `plan.reference_library` supplies a shortlist even without configured template sources. Record adopted references through template_sources/template_refs; keep example achievements out of task facts.

## Minimal planning input

After the approved summary, create the 2.1 Slide Spec in the work directory and call `plan`. This valid single-page shape shows normal fields; replace the example content, facts, number of pages and speaking times from the task. Use the current validator for errors rather than querying the full schema repeatedly.

Pending research does not prevent plan/run/preview: use the formal scaffold and actual tokens, then close adopted evidence before complete. Do not write a second probe generator while waiting for the researcher.

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

The coordinates, size and synthetic wording above illustrate the API, not a page recipe. Replace them from your own material. `presentation_copy` is optional role metadata, not a second required copy of the deck. Actual text/notes are read from PPTX; titleless image pages are valid. Native `slide.addNotes()` and merged/automatically sized `slide.addTable()` are supported. Notes speak selectively and preserve factual boundaries.

## Text and emphasis

`H.addFittedText(slide, value, box, tokens, 'chinese', role, options)` accepts plain text or an array of `{text, options}`. Supply the size you choose; measured pages do not automatically shrink it. `options` supports fontFace, cjkFontFace, fontSize, color, bold, align and margin. Per-run bold/color retains editable inline emphasis — this is the canonical way to highlight key numbers and terms inside a line. Roles identify content, not title/footer zones. To change font families deck-wide (e.g. CJK in Microsoft YaHei), pass `typography` through `plan --art-direction` — it feeds both the inlined TOKENS and the build-time Latin→CJK `<a:ea>` map; a per-call `cjkFontFace` alone does not update that map.

Use size, weight, color and grouping to make a visible speaking path. Choose typography from the viewing conditions and actual renders. Line height uses real font metrics; explicit line/paragraph spacing wins. Font/size counts are reported as context, not style violations; optional legacy threshold warnings require `typographyHeuristics: true`.

A predicted overflow needs comparison with the actual render: improve wording/grouping or geometry without dropping required support. `H.fitText(value, box, H.rolePolicy(tokens, 'chinese', role, options))` returns `fits`, `requiredH`, `lines` and `lineGeometry` without drawing. Ordinary Chinese quotation marks use the Chinese family; explicit run font choices remain binding. Never claim PowerPoint behavior from LibreOffice alone.

`requiredH` is inches; never divide it by 72. Measure with the same width, font, bold and line/paragraph spacing used to draw. Predicted wraps remain native wrapping, not forced paragraphs. Reserve the actual height of a short source citation before allocating body space; detailed source passages and calculations belong in notes/references, not a long paragraph laid over the bottom of the page.

Mixed-language text stays one object by default: CJK and Latin/digit runs render as a single rich-text object with per-run fonts, which is also how you do inline emphasis (bold/color on key numbers and terms within one line). The legacy anti-rewrap split into separately positioned fragments is opt-in via `positionMixedText: true` (options or box level); readback re-joins such fragments by their shared `sps-line:` name. Use the split only for measurement-critical single-line chips, never for wrapped body text — fragment baselines and line pitch follow the font model, not the renderer. A `fact_bindings` metric may use one object or unambiguous nearby label/value objects in the same container. The reader associates mutual nearest neighbours and two-cell table rows; it never concatenates the whole slide. Ambiguous regions need clearer association or author review. Natural positive connectors such as 为/达到 are accepted; negated/comparative claims are not treated as exact facts.

Measurement contract: each line's height comes from the real font metrics of its largest run (`(ascent − descent + lineGap) / unitsPerEm`, falling back to fontSize × 1.18 when metrics are unavailable), and a block's required height is the sum of its lines — so a label line costs the big number's size when they share one block; separate objects price independently. Widths use the real font's advances (CJK ≈ 1 em, Latin ≈ 0.58 em). `fits` uses the selected `maxFillRatio` (1 for model-led helpers, 0.95 for a raw layout call) and requires `requiredH ≤ available height × maxFillRatio` and every line within the margin-reduced width. Optionally measure text before `run` with `python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" measure --work-dir <wd>`; it never draws or builds and reports all overflows and tight margins at once (contrast, overlap and alignment are checked only by `run`).

## Images, diagrams and tables

- `H.addPlannedImage(slide, {path, width, height}, box, pptx)` needs an inspected file and its real pixel dimensions. Default placement preserves evidence; crop deliberately and retain protected regions. Use the asset manifest for provenance and approved placeholders.
- Native `slide.addShape('rect'/'ellipse'/'line', options)` draws editable relationships. `decorative:true, bleed:true` permits an intentionally clipped background shape; it does not permit text/evidence outside the canvas or hiding foreground information.
- For native lines, keep width/height non-negative; use the minimum endpoint coordinates, absolute extents and flipH/flipV for reversed diagonals. Negative extents can produce invalid DrawingML even when the line looks plausible in a render.
- Native `slide.addTable(rows, {x,y,w,h,colW,rowH,fontSize,...})` uses explicit editable cell geometry. Each row is an array; rich cells are `{text, options}`. Provide all column widths and row heights when unequal; merged cells need explicit shapes/text. Do not invent data to fill a table. The first row becomes a header when any of its cells is bold: its fill defaults to `palette.primary_accent` and its text to a relative-best readable candidate — pass `headerFill` and `headerColor` explicitly to control the pair, since the auto-picked combination is not guaranteed to reach the 3:1 contrast floor.
- A flow is nodes + truthful labels + connectors; a comparison is aligned dimensions and supported values. A panel should contain explanation/evidence, not only a large name. See runnable visual examples only for the expression the current material needs.

## Production and inspection

`plan` creates the page functions; `run` builds/checks/renders and returns `check_summary`, `changed_pages`, previews and full-report paths. Read current reports with `status`, not another `run`. Keep JSON stdout separate from logs; save to a real project path rather than a shell-specific `/tmp` name.

Inspect all pages on the first run. After changes, inspect every affected final page in full and the latest contact sheet; `changed_pages` reports changed renders; shared-source edits alone do not label unchanged pages as changed. Then `complete` exports selected deliverables to the planned `output_dir` (default `outputs/<work-id>`), including all slide PNGs when preview is selected. Revise current inputs in the same work-id; substantial Production Summary changes still need confirmation. `complete` refreshes actual checks and derived previews as needed. `status` distinguishes missing exports from user-modified exports.

For one helper, use `node "${CLAUDE_PLUGIN_ROOT}/scripts/pptx-helpers.js" --describe --function addFittedText`. It returns its actual signature, behavior and example. Only inspect a specific implementation after the supported usage cannot resolve a concrete issue.

Implemented page functions may retain a provenance comment; empty functions remain unfinished, and runtime checks require real drawn objects. Mixed-size inline number/unit runs inside one rich-text object keep a single logical line with measured geometry and shared baselines. Never split one logical line into separate positioned boxes to style its parts — separate boxes have independent baselines and line pitch, and hand-compensating their offsets misaligns the line.

## Diagnosing preflight failures

The geometry preflight error is self-contained: each line reads `slide N: code (elementId) [ratio=…, requiredH=…in boxH=…in] — message`, carrying the contrast ratio and background, measured-vs-required height, overlap ratio or alignment delta that makes the failure actionable. Fix from the throw; do not re-derive it from registry source.

- Full detail (warnings, contrast scope, per-element geometry) lives in `<pptx>.registry-report.json` next to the built file. The sidecar is written even when the preflight fails — `writeReport` runs before `assertSafe` — so a failed build still leaves the report on disk next to the output path.
- Trace an element by id: the error line's `elementId` matches `slides[].elements[].id` in the sidecar, which lists the element's `x/y/w/h`, `fontSize`, `role` and measured `lineGeometry`; compare those numbers with the box in the page source to locate the drift.
- Warnings (decorative stripes, size tiers, family mixes) never block the build; they are inspection signals in the same sidecar, not reasons to reverse-engineer the registry.

## Relationships, numeric facts and visual safety

For an optional relationship helper, require `${CLAUDE_PLUGIN_ROOT}/scripts/pptx-relations.js`. Supply actual supported content, box and fontSize; there is no global size or layout recipe:

- `metric(ctx, {label,value,unit,context?}, box, {fontSize,labelSize?,color?})`: editable rich text in one object, suitable for the fact_bindings contract in slide-spec.md — it offers one convenient text carrier; unambiguous spatial association is also supported. The numeric value is a string; label and unit retain their actual meaning.
- `evidenceRows(ctx, [{label,detail}], box, {fontSize,labelWidth?,gap?,rowGap?})`: nearby explanation with a shared reading axis.
- `processSteps(ctx, [{title,rows:[{label,detail}]}], box, {fontSize,titleHeight?,labelWidth?,gap?,rowGap?})`: directional process with explicit inputs/actions/retained evidence; rowGap and horizontal gap are independent.
- `annotatedImage(ctx, asset, [{x,y}], box, {markerFontSize,markerSize?,color?})`: numbered anchors in normalized coordinates on an inspected image. Box must match asset aspect ratio; place markers away from evidence text and explain them nearby. It cannot determine whether a marker hides image content.

`decorative` and `bleed` allow intended background treatment, not opaque foreground masks over text. An accent bar or rule deliberately painted over a panel is a decorative overlay: mark it `decorative: true` so it stays out of `element_overlap` warnings; unmarked, that intentional overlap surfaces as a warning to inspect. Known solid foreground/background contrast below 3:1 is an error; 3–4.5:1 requests size/weight/viewing review. Images, gradients, transparency, unknown colors and partial surfaces remain explicitly unresolved; check their final renders. No global font floor is introduced; body/list below 12pt, caption/source/reference below 9pt, and other text below 10pt raise `text_size_review` warnings (inspect, not block). Complete same-material examples and their limitations are in main-session-visual-examples.md.
