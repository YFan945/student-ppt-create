# Slide Spec YAML

Slide Spec v2 adds layered content, story roles, evidence references, locking,
and revision metadata while remaining backward-compatible with v1 specs. Omit
`schema_version` for legacy input or set it to `"2.0"` for the expanded model.

Use Slide Spec YAML as an optional handoff format when:
- the user says the outline will later become a PPTX
- the deck is complex or group-based
- the user asks for structured output
- the review should compare plan vs actual slides

Do not force YAML for simple outline-only requests.

## Required Fields

Each slide entry must include:
- `id`: slide number
- `title`: claim-style title for argumentative/evidence slides; descriptive title is allowed for cover, divider, quotation, references, appendix, Q&A, and closing slides
- `layout`: adaptable composition hint or slide type; a known catalog ID is not locked by default
- `content`: short on-slide text or structured objects
- `timing_sec`: planned speaking time as an integer number of seconds
- `owner`: speaker/member, or `Individual`

Optional slide fields:
- `layout_lock`: when `true`, use the named catalog layout exactly; omitted/`false` allows the
  producer to alter proportions, zones, shapes, or choose a better related composition
- `kind`: `cover`, `content`, `section-divider`, `quotation`, `references`, `appendix`, `qa`, or `closing`; defaults conceptually to `content`
- `visual`: visual type, purpose, optional `layout_family`, asset/alt text, and structured
  details. In v2/high-score/balanced/visual-led production it is required on content slides;
  exempt slide kinds may omit it when a visual would be decorative.
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
- `image_source`: `"user-assets" | "web-search" | "generated" | "hybrid-adaptive" | "diagram-only" | "text-only" | "ask-before-web-search"`
- `source_material`: a short evidence-boundary description or a list of supplied sources
- `visual_style`: one of the 12 formal style names, `Other`, or a legacy style name
- `visual_style_custom`: required when `visual_style: Other`; carries the confirmed
  `style_character`, six-role `palette`, four `backgrounds`, and `svg_reference`
- `quality_level: high-score` and `visual_text_ratio: balanced|visual-led` require a
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

Optional v2 slide fields:

- `role`: story function such as `problem`, `method`, `result`, `limitation`, or `conclusion`
- `claim`: the one message the audience should remember. It must reach the page as
  visible text, verbatim — the actual-content gate matches PPTX text runs byte-exact,
  so a claim that lives only in this file is undelivered (chart data labels are not
  text runs).
- `supporting_points`: concise reasons, examples, or evidence
- `slide_copy`: final compact PPT wording
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
    fix: "Rename the slide with a claim-style title and reduce body text."
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
- treat `visual.purpose` as required design intent when `visual` is present
- use integer `timing_sec` values to balance speaker notes
- keep `layout` unless a better layout is needed to prevent crowding
- implement `layout` as a functional intent, not a fixed visual template
- split slides or move details into speaker notes when content is dense; do not shrink normal body text below shared typography thresholds to make content fit
- report any spec item that cannot be implemented
- do not invent visuals or transitions for slide kinds where they would be decorative or artificial
- when `source_deck` or `review_findings` is present, treat the spec as an existing-deck improvement plan: preserve listed elements, apply the findings, write a separate improved PPTX, and create `outputs/<topic>-change-summary.md` when required

## Layout Functional Mapping

Use these mappings as intent rules. The final visual form may vary by creative direction.

- `timeline`: must show sequence, phases, or change over time. May use a horizontal timeline, vertical timeline, stepped path, roadmap, process ribbon, or milestone cards.
- `comparison`, `comparison-cards`, `before-after`: must make differences easy to scan. May use side-by-side panels, 2x2 matrix, before/after cards, annotated examples, or contrast bands.
- `process`, `three-step-process`, `loop-diagram`: must show flow, order, or feedback. May use numbered nodes, cycle diagram, path diagram, swimlane, or staged panels.
- `risk-callout`, `limitations`: must identify the risk or boundary and explain why it matters. May use warning callouts, evidence cards, redline annotations, or limitation panels.
- `data`, `chart`, `survey`: must put the conclusion near the chart/table and avoid unexplained raw data. Use one main chart/table per slide.
- `team-workflow`, `handoff`: must show member ownership and speaking flow. May use role lanes, member cards, sequence markers, or workflow arrows.
- `summary-qa`, `closing`: must leave one memorable takeaway and a clear Q&A/closing cue. May use a summary card, final claim, key-number recap, or question prompt.

## Review Rules

When `sp-review` receives Slide Spec YAML plus a deck:
- compare planned title, layout, visual, timing, and owner against the actual deck
- flag missing visuals, changed claims, lost handoff lines, or timing drift
- treat mismatches as risks, not automatic errors, when the final deck improves clarity

## Pipeline research classification

Set top-level `research_scope: A|B|C|D`. A/B/D require a validated Research Pack,
evidence map and runtime-generated researcher receipt at plan. External-source
ledger entries also trigger this requirement even if scope was omitted. C is only
for decks that need no external facts. Source-deck mode is derived from source_deck
and edit_intent; a PDF/image source is rebuilt, never silently treated as create.
