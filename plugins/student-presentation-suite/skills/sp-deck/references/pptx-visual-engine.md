# PPTX Visual Tools

The main session authors pages freely under [model-led-design.md](../../../references/model-led-design.md). Use [main-session-production.md](main-session-production.md) for `plan → run → complete` and [pptxgenjs-helper-api.md](pptxgenjs-helper-api.md) for drawing APIs.

## Optional composition tools

- `pptx-composition.js`: six guided moves (`thesis`, `weighted`, `metric`, `proof`, `sequence`, `figure`).
- `pptx-layouts.js` and `pptx-composer.js`: reusable components and deterministic layouts. `scripts/composer_deck.js` remains a legacy composition runner for compatibility.
- `visual-reference-library.json`: composition examples and rationale.
- `pptx-visuals.js`, `pptx-icons.js`, `pptx-svg-library.js`: editable diagrams, icons and SVG assets.

Choose tools as needed. Their component defaults do not constrain free-page typography, colors, layout, imagery or page rhythm. Art Direction is optional.

## Rendering considerations

Measure text with fontkit and inspect the actual renders. Preserve image aspect ratio or specify an intentional crop. Keep chart labels, units and sources clear; choose axis bounds that represent the data truthfully. PptxGenJS line charts may ignore series-level line width/dash settings, so inspect whether the intended encoding rendered correctly.

Register actual elements and repair real text overflow, clipping and accidental obstruction. Technical checks do not establish visual quality; the main session views every full page and compares supplied references before delivery.
