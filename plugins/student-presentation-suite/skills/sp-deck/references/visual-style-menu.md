# Visual Style Menu

For new tasks, [model-led design](../../../references/model-led-design.md) owns creative freedom and verification. Existing tasks retain their frozen controls.

Visual styles are **user-facing style seeds**, not templates or layout engines. Seeds describe mood, palette and optional assets. The main session chooses typography, imagery, icons, charts and page rhythm from the content and actual renders. Art Direction is optional.

This separation is intentional: users choose a comprehensible visual mood; the model then acts as art director instead of asking the user to configure dozens of design details. Factual integrity, source safety and usable readability remain binding. Preserve required user/template elements and adapt flexible content areas; resolve material conflicts explicitly. Within that boundary, follow the slide's information task, the confirmed style seed and optional Art Direction.

## Intake Categories

This catalogue is optional when the user wants help choosing. Reuse a supplied direction or choose one under delegated preferences; do not require category/subtype rounds. If browsing categories is requested, Step A shows exactly three categories plus `Other`; Step B shows all four styles in the selected category.

| Category | Four available styles |
| --- | --- |
| Academic and professional / 学术与专业类 | Academic Rigorous, Data Driven, Modern Minimal, Charcoal Editorial |
| Business and technology / 商务与科技类 | Midnight Business, Ocean Tech, Teal Trust, Cherry Bold |
| Creative and humanistic / 创意与人文类 | Creative Student, Coral Energy, Forest Moss, Warm Terracotta |
| Other / 其他 | Free user description; the AI completes and confirms the required custom seed |

Do not expose old “show all styles”, cross-category markers, or multi-round style lists. Recommend the category and style that best fit the topic, and include the actual direction in the approved summary.

## Style Seed Contract

Each file under `visual-styles/` supplies these lightweight authoring inputs:

1. `Style character`
2. `Palette`
3. `Font families`

Background and SVG preferences are optional custom inputs, not required fields in each seed. The style character describes the mood and emphasis; it must do more than repeat the style name. Use it as direction, not as a mandatory layout.

Palette roles are `canvas`, `surface`, `primary_text`, `secondary_text`, `primary_accent`, and `secondary_accent`. These files intentionally stay compact. **They are no longer the final design specification.** In new tasks, concrete design decisions live in authored pages; an optional `art-direction.yaml` may record reusable preferences.

### Light and dark are one scheme, not two

Every style carries **two** six-role palettes: the light `palette` and a matching
`dark_palette`; the author chooses where to use each. The dark scheme is derived from the same
hue family as the light one, so a deck never reads as "dark cover glued to unrelated light body
pages". `resolve_design_tokens()` guarantees a dark companion for every style; custom and legacy
styles get one derived automatically, and a supplied `dark_palette` is contrast-checked exactly
like the light palette.

Both palettes must clear the same floors: `primary_text` and `secondary_text` at 4.5:1 against
both `canvas` and `surface`, and `primary_accent` at 3:1 against both.

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

The example includes optional background and SVG choices. Only style character and the base palette are required; additional semantic colors are allowed. Omit unused backgrounds and SVG motifs. Show the actual visual direction in the Production Summary. Art Direction is optional in new main-session tasks; do not require another style questionnaire.

## Compatibility

- `Berry Cream` / `berry-cream` resolves to `Warm Terracotta` with a compatibility warning.
- `Sage Calm` / `sage-calm` resolves to `Forest Moss` with a compatibility warning.
- Any other historical unknown style retains its name as `style_character`, uses the Modern Minimal safety seed, and emits a compatibility warning.

## Style inputs

The current catalog contains colors and font families. It contains no page regions, font-size table, panel treatment, motif placement, chart grammar or decoration recipe. Page composition comes from the source material and the user's references.

## Template Inheritance

When the user supplies a school template, preserve required logo, footer, colors, cover and useful placeholders. The template takes priority over the style seed. Art Direction should then describe how to use the template well rather than force unrelated colors, motifs, cropping or component language into it.

For object-level inheritance and the distinction between template, inspiration and content-only input, read `cover-and-template.md`.
