# PPTX Art Direction — v0.8

Art Direction is the bridge between a lightweight visual style seed and concrete slide design. It is produced **after Slide Spec freeze and before any final `deck.js` is authored**. Its job is to turn vague words such as “academic / modern / creative” into a coherent, executable visual language for the whole deck.

The selected `visual-styles/<style>.md` remains a seed for character, palette and background. Art Direction must resolve the choices that the old style layer intentionally left unspecified: typography scale, image treatment, icon language, chart grammar, component language, motif, background rhythm, density rhythm and visual asset strategy.

## Required artifact

Create `outputs/.pptx-work/<work-id>/art-direction.yaml` before final composition. It is a production artifact, not a user-facing preference questionnaire. Do not ask the user to choose every field; infer a strong coherent direction from the confirmed Production Summary, frozen Slide Spec, selected visual style and design grammar.

Minimum contract:

```yaml
version: "0.8"
concept: "Evidence-first editorial classroom deck: confidence is not truth"
style_seed: "Academic Rigorous"
grammar: "coursework"

color_system:
  dominant_role: "canvas"
  dominant_share_pct: 65
  contrast_mode: "dark-light-sandwich"
  accent_usage: "Only evidence, key numbers and selected navigation cues"

typography:
  personality: "editorial sans with restrained serif accent"
  cover_title_pt: 52
  slide_title_pt: 34
  key_statement_pt: 30
  body_pt: 19
  caption_pt: 10
  title_body_ratio: 1.79
  emphasis_methods: ["size", "weight", "position"]

imagery:
  strategy: "evidence-first with conceptual hero visuals"
  crop_language: "half-bleed / edge crop; avoid small floating stock photos"
  treatment: "natural color, no generic gradient overlays"
  subject_priority: ["user evidence", "real figures/screenshots", "conceptual illustration"]

icon_language:
  usage: "small navigation/semantic accents only"
  style: "single-weight line icons"
  max_per_slide: 3

chart_grammar:
  default: "native PowerPoint chart with one highlighted series"
  labels: "direct labels where possible"
  gridlines: "quiet or removed"
  takeaway: "one sentence or one number dominates the chart"

component_language:
  cards: "exception, not default"
  borders: "hairline only for evidence grouping"
  radius: "small or none"
  shadows: "none by default"
  separators: "whitespace first; thin rule only when semantic"

motif:
  name: "evidence rail"
  description: "A repeated bracket/caption treatment that marks sourced evidence"
  allowed_on: ["cover", "evidence", "closing"]

background_rhythm:
  - role: cover
    mode: dark
  - role: content
    mode: light
  - role: evidence
    mode: light
  - role: section
    mode: accent
  - role: closing
    mode: dark

asset_plan:
  hero_visuals: 2
  evidence_visuals: 3
  diagrams: 2
  native_charts: 1
  typography_led: 1

high_leverage_slides:
  - slide: 1
    reason: "Cover establishes the visual thesis and first impression"
  - slide: 2
    reason: "Hook/case page must create curiosity immediately"
  - slide: 5
    reason: "Central evidence page determines credibility"
  - slide: 8
    reason: "Closing must visually callback to the opening thesis"

avoid:
  - "equal cards as the default mapping for parallel bullets"
  - "all slides sharing the same title/body silhouette"
  - "filler icons or decorative photos"
  - "tiny text caused by over-dense content"
```

The exact values can differ, but all major sections above must exist in high-score create/rebuild mode.

## Positive design priors

Art Direction must describe **what to do**, not only what to avoid.

### 1. Establish visual dominance

Every deck needs a dominance model. One background/color family should carry roughly 55–75% of the visual weight. Accent colors must be scarce enough to mean something. Avoid distributing four or more colors at equal strength.

### 2. Use a strong type scale

For 16:9 classroom/research decks, default ranges are:

- cover title: 44–60pt
- slide title: 30–38pt
- key statement / large takeaway: 28–42pt
- body: 17–22pt Chinese, 16–20pt English when readability allows
- caption/source: 9–12pt

Title/body hierarchy should normally be at least about 1.45× in perceived size. Do not let a safety minimum silently collapse title and body to nearly equal sizes.

### 3. Decide an imagery language

Do not merely say `use images`. Decide how images behave:

- full-bleed / half-bleed / edge crop / inset figure / annotated screenshot;
- natural photo / diagram / technical screenshot / generated conceptual illustration;
- square, portrait or panoramic bias;
- whether text overlays are allowed and how contrast is created.

Small unrelated floating images are usually weaker than one decisive crop.

### 4. Decide a chart language

A chart should not inherit PowerPoint defaults. Art Direction decides whether the deck uses direct labels, one accent series, quiet gridlines, data callouts, figure captions and source placement. The chart exists to prove one claim, not to display every available metric.

### 5. Decide component behavior

Cards, pills, icon circles, borders and shadows are components, not a default page grammar. State when they are appropriate and when whitespace, alignment, type and images should carry structure instead.

### 6. Plan deck rhythm before page coordinates

A good 8–12 slide deck should normally alternate among several visual energies, for example:

```text
cover hero
→ editorial claim
→ diagram/process
→ typography contrast
→ evidence/chart
→ annotated image
→ comparison/trade-off
→ closing callback
```

Do not generate eight individually acceptable pages that all have the same visual energy.

## High-leverage slides

Before writing the final deck, mark 3–5 slides in `high_leverage_slides`. Typical choices are cover, first problem/hook, central mechanism/framework, strongest evidence/result and conclusion/closing. Every entry needs a valid Slide Spec `slide` number and a concrete `reason`.

These pages must go through v0.8 multi-candidate composition. This list is also consumed by `pptx_visual_generation_gate_v08.py`; therefore it is production evidence, not informal notes. Ordinary lower-risk slides may use one composition after reference retrieval.

## Asset budget

Visual richness must be planned, not improvised at the end. For a typical 8-page high-score deck, aim for a deliberate mix such as 2 hero/evidence images, 1–2 native charts, 1–2 diagrams, and 1 typography-led page where content supports it. These are not quotas; the point is to prevent the generator from falling back to text boxes and rectangles on every page.

Use user assets and sourced evidence first. `pptx-icons.js`, `pptx-visuals.js`, native charts and custom SVG are deterministic internal assets. Web/search/generated imagery remains conditional on user permission and available tools.

## Relationship to other layers

- **Visual style seed**: color/character/background starting point.
- **Design grammar**: narrative/page-language rules for the scenario.
- **Art Direction**: concrete deck-wide visual decisions.
- **Visual Reference Library**: proven composition recipes that make Art Direction tangible.
- **Composition candidates**: alternative page solutions for high-leverage slides.
- **Actual Element Registry / QA**: engineering and final artifact safety.

Art Direction must not contain final x/y/w/h coordinates. It is a design brief for composition, not a second layout engine.
