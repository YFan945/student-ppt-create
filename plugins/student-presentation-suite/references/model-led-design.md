# Model-led design and frozen information (Slide Spec 2.1)

New tasks use `meta.design_freedom: auto`; `quality_level` controls verification
effort independently. Existing 1.0/2.0 specs and work-id snapshots keep their
original copy and production policies; do not migrate them implicitly.

| Mode | Page module | Composition |
| --- | --- | --- |
| auto | render function with `presentation_copy` and `notes` | Free coordinates, shared helpers or direct drawing |
| guided | declarative object with `move` | Existing six moves |
| deterministic | declarative object with `layout` | Existing layout library and components |

The shared page harness owns the base background, actual element capture,
speaker notes and build/copy reports. Every drawn text, shape, image and chart
must have valid geometry. Supply a finite positive font size. No mode imposes a
product font floor or title/body ratio on new tasks. `H.addFittedText` uses actual
fontkit glyph advances; it reports required height and box geometry when copy
does not fit. The Builder may change font size, box, composition or expression.
Typography, palette proportions, motif, panel treatment, cover bands, repeated
moves and gallery examples are design suggestions. The gallery is an optional
reference and failure fallback, never a visual ceiling or required treatment.
Guided fit failures return geometry to the Builder; they do not silently switch
to a template. Only the recorded per-page downgrade changes production mode.
Record the chosen visual language in Art Direction. User-specified branding,
template, logo and `preserve` remain hard constraints; the critic verifies them
against the current pages. Store explicit `brand`, `logo` and `template` in the
Brief and Spec meta; the bridge preserves them and the critic preview map projects
them as `user_constraints`. On new contracts handoff rejects changed values.
Actual unreadability, overlap, missing content,
contrast, damaged PPTX structure and source errors still block delivery.
`rigorous` asks for more thorough verification, not more templates. Subjective
low scores alone are advisory.
For model-led reports, every finding must specify `category`: design_preference
is advice; readability, fact, structure and user_constraint retain blocking
severity. `structure` describes an actual PPTX or element geometry defect,
not a preferred treatment.
Changed facts or user constraints block even if a critic assigns minor severity.
Unsupported quantitative bar/area ratios are factual errors, not design advice.
Final delivery keeps the Spec and Art Direction hash bindings, while optional
gallery selections, composition candidates and wireframes need no file hashes.
Reports with missing decisions, stale input binding or unbound quotations are
returned to the independent critic for correction, without a Builder round.

## Information contract

Every 2.1 page has `semantic_requirements`:

```yaml
semantic_requirements:
  must_convey:
    - id: low-year-research
      text: 为低年级提供科研实践机会
      evidence_refs: [E1]
      placement: slide
  must_show_exact: [国家奖学金, '233']
```

Ids are stable within a page. `placement` defaults to `slide`; only explicitly
marked supplementary information may go to `notes`. Link evidence whenever a
requirement depends on a source. Core claims and their numbers cannot disappear
into notes. Numbers mentioned in on-slide requirements also become exact token
checks. `233` cannot match `1233`, `233.1` or `1,233`.

Planning title, claim and long copy are inputs for interpretation, not required
verbatim strings. Actual headline, visual labels and speaker notes go into
`presentation-copy.json`, bound to the normalized PPTX. It is a record of actual
copy, not a Builder certificate of semantic coverage. Source and PPTX readback
share one requirements parser. Wrapping whitespace may differ; facts may not.
Positioned language spans carry `sps-line:` OOXML names. Readback joins only
consecutive spans in that logical line with matching y coordinates and adjacent
x geometry; unrelated text boxes remain separate numeric tokens.

The isolated critic receives current rendered pages, actual text, actual notes,
frozen requirements, evidence and registered element ids in its preview map.
For **every** required id, emit `semantic_coverage` with `status` (`covered`,
`missing`, `contradicted`), assigned `placement`, and `actual_excerpt`, or
`visual_elements` when a diagram/image conveys the information. Explain any
omission or contradiction. A visual id must exist in the actual registry and
the critic must inspect its rendering. Missing coverage decisions, missing core
information and changed facts block every tier. Copy `semantic_binding` from
the preview map. Reports bind Spec, PPTX, rendered page and notes hashes; any
changed input invalidates incremental reuse. QA also binds the copy sidecar,
so changing it after QA requires QA again.

## Text and assets

Measured wrapping preserves explicit paragraphs and rich-text emphasis. Keep
numbers with units and Latin words together, respect Chinese opening/closing
punctuation, and balance very short last lines where geometry permits.
Chinese lexical segments use the runtime's word segmentation to keep terms
such as 检索/重排/回答 together; guided composition also enables measured
last-line balancing by default.
Emit explicit line breaks, never zero-width characters. Drawing and Registry consume
the same line geometry. Font resolution/substitution is recorded, including TTC
faces. For viewers that add unwanted CJK/Latin spacing, use
`H.addPositionedText` to place measured language fragments with a logical line
owner. Mixed lines and paragraphs use positioned language spans automatically;
`positionMixedText: false` retains a single text box when the target viewer is
verified to honor its line breaks. Registry keeps the logical paragraph box
for alignment and individual drawn spans for overflow/overlap. Actual rendering
remains necessary after font measurement.

Record source image `width`/`height`, `content_focus`, normalized `focal_point`,
`preserve_region` and `crop_suggestion` in `asset-manifest.json`. Decide layout
after inspecting the actual asset. Certificates, screenshots and paper figures
must retain key information. `H.addPlannedImage` uses contain for protected
assets; an explicit crop must contain the protected region. No fixed picture
quota or additional move/template is introduced.

## Repair policy

Keep the existing repair budget. First repair uses the current mode. When the
same page and class of composition/fit blocker recurs after repair, downgrade
that page `auto → guided → deterministic`, record the reason in
`build-manifest.json.design_state`, and replace only that affected page module.
Do not downgrade to bypass facts, sources or receipts. Budget exhaustion returns
`incomplete`; it never silently extends the budget or certifies delivery.
Refreshing QA evidence while a repair is pending keeps that same repair and
its count; derived gate summaries do not expand the page assignment.

Reproducible fixtures and evaluation methodology live in
`examples/design-benchmarks/`; generated PPTX/PNG artifacts stay outside the
marketplace repository.
