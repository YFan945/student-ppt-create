# Slide Spec YAML

For new tasks, [model-led design](model-led-design.md) owns creative freedom and verification. Existing tasks retain their frozen controls.

New handoffs use `schema_version: "2.1"`: freeze semantic requirements and exact items while allowing authored presentation wording. Keep existing 1.0/2.0 inputs in their original contract; never silently migrate them. Legacy-only rules are separated below.

Use Slide Spec YAML as an optional handoff format when:
- the user says the outline will later become a PPTX
- the deck is complex or group-based
- the user asks for structured output
- the review should compare plan vs actual slides

Do not force YAML for simple outline-only requests.

## Required Fields

Each slide entry must include:
- `id`: slide number
- `title`: choose a direct subject title for definitions, mechanisms, setup and process; use a supported takeaway where the page establishes a finding. Cover, divider and reference titles may be descriptive. Do not force every page into an insight or repeat a conclusion.
- `layout`: optional composition hint for 2.1; required on legacy input without semantic requirements. A known catalog ID is not locked by default
- `content`: complete visible authoring material or structured objects, with no automatic length cap
- `timing_sec`: planned speaking time as an integer number of seconds
- `owner`: speaker/member, or `Individual`

Optional slide fields:
- `layout_lock`: when `true`, use the named catalog layout exactly; omitted/`false` allows the
  producer to alter proportions, zones, shapes, or choose a better related composition
- `kind`: `cover`, `content`, `section-divider`, `quotation`, `references`, `appendix`, `qa`, or `closing`; defaults conceptually to `content`
- `visual`: type, purpose, asset/alt text and structured details. Actively plan topical imagery, editable tables/charts/diagrams and permitted designed placeholders. The scaffold passes visual intent and data to the author; purpose is planning prose, not display copy. New 2.1 pages do not use legacy payload-width or component-count quotas.
- `note_goal`: what the speaker note should accomplish
- `transition`: transition or handoff sentence; omit on the final slide or when no meaningful transition exists

Optional deck-level `meta` may carry confirmed constraints across planning, PPTX production, and review:

Meta field rules:
- Recommended required fields: `topic`, `presentation_type`, `language`,
  `duration_min`, and `format`
- Optional fields: `slide_count`, `members`, `course`, `audience`, `rubric`,
  `source_material`, `template`, `logo`, `image_source`, `visual_style`, `visual_style_custom`,
  `deliverables`, and `output_prefix`
- v2 control fields: `scenario`, `audience_type`, `audience_depth`,
  `structure_mode`, `interaction_mode`, `quality_level`,
  `max_words_per_slide`, `max_chinese_chars_per_slide`, `visual_text_ratio`,
  `include_speaker_notes`, `include_key_lines`, `citation_style`,
  `export_formats`, and `versioning`
- `language`: `"Chinese" | "English" | "bilingual"`
- `format`: `"individual" | "group"`
- `duration_min`: number of minutes
- `slide_count`: integer target slide count
- `max_words_per_slide` / `max_chinese_chars_per_slide`: optional confirmed positive-integer limits, without arbitrary upper bounds; omit for new tasks with no user cap. Explicit values remain binding; legacy defaults remain supported.
- `image_source`: `"user-assets" | "web-search" | "generated" | "hybrid-adaptive" | "diagram-only" | "text-only" | "ask-before-web-search"`
- `source_material`: a short evidence-boundary description or a list of supplied sources
- `visual_style`: one of the 12 formal style names, `Other`, or a legacy style name
- `visual_style_custom`: required when `visual_style: Other`; carries confirmed
  `style_character` and a base `palette` with optional semantic category colors.
  `backgrounds`, `dark_palette` and `svg_reference` are optional; only declare used choices.
- New 2.1/model-led tasks require non-empty diagram data when declaring a structured visual, without stage/item quotas; chart metadata, numeric values and matching labels remain checked. `supporting_points` has no count cap. The following component-count guidance applies to legacy specs.
- Legacy `quality_level: rigorous` (legacy `high-score`) and `visual_text_ratio: balanced|visual-led` require a
  meaningful structured `visual` for every content slide. `timeline` needs 3+ stages;
  `comparison` needs 2+ items plus dimensions; `process` needs 2+ steps; `chart` needs
  measure, unit, scope, source, and takeaway. Architecture/swimlane needs 2+ nodes,
  cycle needs 3+ steps, matrix needs 2+ items, and annotated-image needs an asset.
- `visual.layout_family` is one of `hero`, `visual-dominant`, `process-path`, `timeline`,
  `comparison`, `dashboard`, `architecture`, `matrix`, `quote`, `summary`, or `reference`.
- `deliverables`: 与 Presentation Brief 共用确认后的输出名称集合；`export_formats`
  仅记录实际文件导出格式。编辑任务仍以 `change_summary_required: true` 强制 change summary。
- Use short ASCII-safe `output_prefix` when a later PPTX output filename needs a stable slug.
- For PPTX work, populate meta from the explicitly confirmed Production Summary
  defined in `presentation-intake.md`; do not turn unconfirmed recommendations
  into a Slide Spec.

Optional top-level fields for existing deck improvement:
- `source_deck`: path or label of the original PPTX/PDF/preview being improved
- `edit_intent`: `"review-fix" | "content-rewrite" | "visual-redesign" | "template-adapt" | "rebuild-clean-copy"`
- `review_findings`: structured issues from `sp-review`; each item should include `severity`, `target`, `problem`, and `fix`
- `preserve`: required elements to keep, such as template, logo, footer, citations, approved slide order, or strong existing content
- `change_summary_required`: set to `true` when the PPTX workflow must write `outputs/<topic>-change-summary.md`

## New 2.1 slide semantics

Each slide has `semantic_requirements.must_convey` with stable id/text and optional placement/evidence_refs, plus `must_show_exact`. Core meaning defaults to visible placement; supplementary oral requirements can use notes. A concise note may omit non-spoken slide detail without losing visible coverage. `title`, `content`, `slide_copy`, `visual` and notes are authoring material; actual wording is recorded in `presentation_copy`. `claim` is optional planning input, not a required second visible conclusion or fixed band.

## Legacy 1.0/2.0 copy compatibility

The following verbatim copy and band rules describe existing legacy work only. New 2.1 tasks use the semantic contract above.

Optional legacy v2 slide fields:

- `role`: story function such as `problem`, `method`, `result`, `limitation`, or `conclusion`
- `claim`: the one message the audience should remember. It must reach the page as
  visible text, verbatim — the actual-content gate matches PPTX text runs byte-exact,
  so a claim that lives only in this file is undelivered (chart data labels are not
  text runs).
  **Whether it may restate `title` depends on the page kind.**
  - Legacy argumentative / evidence slides: no. A separate claim must add supported information beyond the title. A
    duplicated claim prints the same sentence twice, wastes the claim band, and is
    flagged by the optional legacy `copy_fit_preflight.py` as `claim_duplicates_title` (major).
  - Descriptive-title kinds (`cover`, `section-divider`, `quotation`, `references`,
    `appendix`, `qa`, `closing`): yes, and it is normal. There the title *is* the
    takeaway line, the page prints it once, and `claim` repeats it so the verbatim
    actual-content gate has the sentence to match — see `examples/golden-sample`.
    Nothing is printed twice and the density cap counts it once.
  - `title` and `claim` both count toward the density cap; an exact duplicate is
    counted once because the page renders it once.
- `supporting_points`: concise reasons, examples, or evidence
- `slide_copy`: final compact PPT wording — **a single string or a list of strings**.
  An object (`{title, subtitle}`) is rejected by the schema, which reads as
  `is not valid under any of the given schemas`; flatten it to a list instead.
- `speaker_notes`: speakable explanation rather than an essay
- `key_line`: optional memorable sentence
- `evidence_refs`: ids from the top-level Evidence Ledger
- `locked` and `lock_reason`: prevent later optimization from changing approved content

Optional v2 top-level fields:

- `evidence_ledger`: traceable sources with confidence and slide usage
- `revision`: revision id, parent revision, and reason
- `revision_operation`, `target_slides`, and `target_section`: constrain local
  rewrite, compression, expansion, evidence addition, section rewrite, or style changes

Schema and validation:
- JSON Schema: `references/slide-spec.schema.json`
- Validator: `scripts/validate_slide_spec.py`
- The validator requires `jsonschema` and `PyYAML` from `requirements.txt`.
- Unknown fields are rejected in `meta`, slides, visuals, and review findings to catch spelling mistakes.
- Semantic validation also checks contiguous slide ids, `slide_count`, total timing vs `duration_min`, group members/owners, existing-deck combinations, high-score controls, evidence references, and lock semantics.
- Current `plan` validates the Spec, compiles evidence when needed and prepares source modules; it does not invoke `copy_fit_preflight.py`. That script is an optional legacy preflight. New-page fit and exact-content checks use authored geometry, readback and actual renders, not fixed title/claim bands.
- **Which file to validate:** for a research-backed deck `plan` compiles your source spec into `slide-spec-compiled.json` and freezes *that* file. Current `plan` validates both source and compiled input itself. When validating by hand, check the source and let `plan` own the compiled input.
- Scenario-driven story roles（如 `defense` 的 problem/method/result/solution/limitation/qa）是**建议性**的，不再作为硬错误阻断：`validate_slide_spec.py` 不因缺失角色失败，`analyze_presentation_spec.py` 会以 Minor 提示。不要为了凑满角色而硬塞一页。

```powershell
python "${CLAUDE_PLUGIN_ROOT}/scripts/validate_slide_spec.py" path/to/slide-spec.yaml --json
```

Optionally run advisory story, density, wording, and evidence checks with:

```powershell
python "${CLAUDE_PLUGIN_ROOT}/scripts/analyze_presentation_spec.py" path/to/slide-spec.yaml --json
```

```yaml
meta:
  topic: "How students use generative AI responsibly"
  presentation_type: "coursework report"
  language: "Chinese"
  duration_min: 8
  slide_count: 10
  format: "group"
  members: ["A", "B", "C", "D"]
  course: "Introduction to AI"
  audience: "Teacher and classmates"
  source_material:
    - "Course brief"
    - "Team development log"
  image_source: "ask-before-web-search"
  visual_style: "Academic Rigorous"
  deliverables: ["pptx", "speaker-notes", "preview", "change-summary"]
  output_prefix: "ai-class-demo"
source_deck: "original-report.pptx"
edit_intent: "review-fix"
preserve:
  - "course logo and footer"
  - "approved section order"
change_summary_required: true
review_findings:
  - severity: "Major"
    target: "Slide 4"
    problem: "The title is generic and does not state the conclusion."
    fix: "Use a supported takeaway title and reorganize the evidence while preserving useful detail."
```

## Example

```yaml
slides:
  - id: 3
    title: "Convenience is the main reason students choose short videos for news"
    layout: "comparison"
    content:
      bullets:
        - "Fast updates"
        - "Low reading effort"
        - "Easy sharing"
    visual:
      type: "bar-chart"
      purpose: "Compare the top three survey reasons"
    note_goal: "Explain the survey result without reading every number"
    transition: "But convenience also creates a reliability problem."
    timing_sec: 50
    owner: "Member B"
```

## PPTX Handoff Rules

When `sp-deck` receives Slide Spec YAML:
- preserve slide order and ownership
- treat `visual.purpose` as required design intent when `visual` is present; it is
  planning prose for the implementer and is never rendered as on-screen text
- use integer `timing_sec` values to balance speaker notes
- implement `layout` as a functional intent, not a fixed visual template
- adapt typography and layout to preserve useful content and rendered readability
- report any spec item that cannot be implemented
- do not invent visuals or transitions for slide kinds where they would be decorative or artificial
- when `source_deck` or `review_findings` is present, treat the spec as an existing-deck improvement plan: preserve listed elements, apply the findings, write a separate improved PPTX, and create `outputs/<topic>-change-summary.md` when required

## Layout information

For new tasks, layout names record the author's intended information relationship. They do not choose a template or require a title, final claim, card count or conclusion band. Implement the supplied information from the material; preserve layouts only when the user explicitly requires them.

## Review Rules

When `sp-review` receives Slide Spec YAML plus a deck:
- compare planned title, layout, visual, timing, and owner against the actual deck
- flag missing visuals, changed claims, lost handoff lines, or timing drift
- treat mismatches as risks, not automatic errors, when the final deck improves clarity

## Pipeline research classification

Set top-level `research_scope: A|B|C|D`. A/B/D require a validated Research Pack,
evidence map. The research skill maintains its own runtime-generated researcher receipt. External-source
ledger entries also trigger this requirement even if scope was omitted. C is only
for decks that need no external facts. Source-deck mode is derived from source_deck
and edit_intent; a PDF/image source is rebuilt, never silently treated as create.
