# Visual Style Menu

Visual styles are **user-facing style seeds**, not templates or layout engines. Each seed keeps the intake simple by describing character, a light six-role palette, its dark companion for cover/section/closing pages, background treatment and one optional SVG motif. After the user confirms the seed, v0.8 **must expand it through `pptx-art-direction.md`** into concrete typography scale, image treatment/crop language, icon language, chart grammar, component behavior, motif use, background rhythm and asset mix before final composition.

This separation is intentional: users choose a comprehensible visual mood; the model then acts as art director instead of asking the user to configure dozens of design details. Apply priorities in this order: approved school/user template → readability/source safety/truthful representation → slide narrative task → confirmed style seed → generated Art Direction.

## Intake Categories

Step A shows exactly three categories plus `Other`. Step B shows all four styles in the selected category in one question.

| Category | Four available styles |
| --- | --- |
| Academic and professional / 学术与专业类 | Academic Rigorous, Data Driven, Modern Minimal, Charcoal Editorial |
| Business and technology / 商务与科技类 | Midnight Business, Ocean Tech, Teal Trust, Cherry Bold |
| Creative and humanistic / 创意与人文类 | Creative Student, Coral Energy, Forest Moss, Warm Terracotta |
| Other / 其他 | Free user description; the AI completes and confirms the required custom seed |

Do not expose old “show all styles”, cross-category markers, or multi-round style lists. Recommend the category and style that best fit the topic, but keep the final seed choice with the user.

## Style Seed Contract

Each file under `visual-styles/` retains exactly these lightweight intake fields:

1. `Style character`
2. `Palette`
3. `Background reference`
4. `SVG reference`

Palette roles are `canvas`, `surface`, `primary_text`, `secondary_text`, `primary_accent`, and `secondary_accent`. These files intentionally stay compact. **They are no longer the final design specification.** After confirmation, `art-direction.yaml` owns the concrete positive design decisions that previously had no home.

### Light and dark are one scheme, not two

Every style carries **two** six-role palettes: the light `palette` for content pages and a matching
`dark_palette` for the cover, section and closing pages. The dark scheme is derived from the same
hue family as the light one, so a deck never reads as "dark cover glued to unrelated light body
pages". `resolve_design_tokens()` guarantees a dark companion for every style; custom and legacy
styles get one derived automatically, and a supplied `dark_palette` is contrast-checked exactly
like the light palette.

Both palettes must clear the same floors: `primary_text` and `secondary_text` at 4.5:1 against
both `canvas` and `surface`, and `primary_accent` at 3:1 against both.

### The shared visual system

The style files describe *character and colour only*; the deck-wide system is shared and is
expressed the same way in every style:

- **Type scale**: 40pt cover / 32pt page title / 26pt statement / 22pt body / 11pt caption, so
  hierarchy is visible instead of title≈body.
- **Accent semantics**: the accent marks the emphasised line, the recommended option, the key
  number and the conclusion node — never decoration.
- **Background rhythm**: dark cover → light content → dark section → dark closing.
- **Evidence rail motif**: a thin accent rule plus caption marks sourced or constructed evidence.

Because the CJK body floor is 22pt, a page title must be at least 32pt to satisfy the 1.45×
hierarchy requirement; this is why the scale starts where it does.

Art Direction may strengthen or refine the seed while keeping its recognizable character. For example, `Academic Rigorous` can become “dark editorial cover + light figure-led evidence pages + Cambria/Arial hierarchy + half-bleed research figures + one evidence-rail motif” rather than merely “navy + blue accent.”

## Other / Custom

When the user selects `Other`, set `visual_style: Other` and complete this structure during intake:

```yaml
visual_style_custom:
  style_character: "风格关键词和整体气质"
  palette:
    canvas: "FFFFFF"
    surface: "F5F5F5"
    primary_text: "111111"
    secondary_text: "555555"
    primary_accent: "2563EB"
    secondary_accent: "93C5FD"
  backgrounds:
    cover: "封面背景说明"
    content: "普通内容页背景说明"
    section: "章节页背景说明"
    closing: "结尾页背景说明"
  svg_reference:
    name: "SVG 母题名称或 none"
    usage: "建议使用位置和强度"
```

The Production Summary must show all four seed sections before confirmation. After confirmation, custom styles follow the same Art Direction expansion as formal seeds; do not ask a second long style questionnaire.

## Compatibility

- `Berry Cream` / `berry-cream` resolves to `Warm Terracotta` with a compatibility warning.
- `Sage Calm` / `sage-calm` resolves to `Forest Moss` with a compatibility warning.
- Any other historical unknown style retains its name as `style_character`, uses the Modern Minimal safety seed, and emits a compatibility warning.

## Optional SVG Toolbox

Each formal seed points to one recommended SVG name. It is only a motif seed. Art Direction decides whether the motif becomes part of the actual deck language and where it is allowed. Do not insert SVG solely to prove the style was selected, and never substitute ornamental SVG for evidence, a chart, a diagram or a meaningful image.

## Reference and Layout Independence

The 36-layout registry remains an inspiration/deterministic-fallback catalog. In v0.8 the stronger positive prior is `visual-reference-library.json`: reference recipes include a rationale, focal ownership, silhouette and normalized wireframe. `visual_reference_select.py` ranks them by slide role, grammar, visual strategy, density, tags and recent visual history. Neither reference recipes nor old layouts are fixed templates; the selected composition is adapted to the slide claim and Art Direction.

## The shared visual system and per-style language

Beyond the two palettes, each style declares a `visual_language` in
`references/design-tokens.json`: how its accent rules are drawn (`bracket`,
`left-rail`, `underline-left`, `top-band`, `slash`), how panels are treated
(`outlined`, `flush`, `soft-fill`, `edge-band`), its corner radius, where the
style's SVG motif sits (`corner-tr`, `corner-bl`, `edge-right`), its signature
chart grammar (`columns`, `line`, `bars`) and its decoration density
(`restrained`, `balanced`, `expressive`). This is what makes the same layout
read differently across styles while staying one system.

**Rendered exemplars:** `examples/visual-template-gallery/` renders 9 template
pages per style (108 pages total) from the layout library and these tokens.
Before composing a deck, consult the rendered pages of the selected style as
the visual ceiling reference; copy the *treatment* (type scale, rule placement,
panel handling, motif use), never the sample copy.

## Template Inheritance

When the user supplies a school template, preserve required logo, footer, colors, cover and useful placeholders. The template takes priority over the style seed. Art Direction should then describe how to use the template well rather than force unrelated colors, motifs, cropping or component language into it.
