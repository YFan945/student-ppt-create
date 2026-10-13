# Content-rich visual examples

Use these examples when content calls for grouped evidence, relationships or an actionable comparison. They demonstrate richer editable composition, not a required template, font scale, palette or asset quota. Choose sizes and density by reading the actual full-size render. A simple cover does not justify reducing all content pages to large sentences.

Runnable page functions are in `../../../examples/main-session-visuals/pages.js`. A page module can export one of its functions:

```javascript
const path = require('node:path');
const examples = require(path.join(process.env.CLAUDE_PLUGIN_ROOT,
  'examples/main-session-visuals/pages.js'));
module.exports = examples.relationship;
```

The examples supply `presentation_copy` and notes for their synthetic teaching content. When adapting, change both to match your facts and final wording. Do not present sample observations as research. Preserve frozen numbers and evidence, and do not add unsupported proportions or conversion rates.

| Page function | Use when | Information carried by the visual |
| --- | --- | --- |
| `relationship` | Several categories connect to one common goal | Multicolor nodes, labeled links and supporting explanations show the relationship |
| `groups` | Several parallel topics each need evidence and interpretation | Color-coded columns with semantic icons, compact explanations and an editable table |
| `evidence` | A real photo, screenshot or research figure needs explanation | An image kept in proportion, numbered annotations and nearby explanation groups |
| `actions` | Problems should map to concrete next steps | Aligned numbered rows connect each problem to its action and acceptance condition |

`../../../examples/main-session-visuals/rich-pages.js` adds `cover` (long semantic title, grouped metadata and optional illustration), `richTechnical` (image + editable table + process + explanatory groups with short notes), `comparison` (flat editable evidence table) and `designedPlaceholder` (topical editable scene, visible label and replacement record). Image functions use `ctx.exampleAsset`; the placeholder function needs no provider. Adapt its `asset_record.slide`, confirm permission and register it in the asset manifest rather than treating a missing image as fetched evidence. See `cover-and-template.md` for strict template reuse.

`photoProcess` uses `ctx.exampleAssets` (four supplied image records with dimensions and optional truthful labels) for a photo montage plus editable process and conclusion. Four is this example's geometry, not a quota. Inspect each image before selecting it and keep its provenance/context.

`shortCover` provides a short-title variant of `cover`. Both are examples of title/metadata/image hierarchy, not a font scale or a required arrangement; inspect the actual title length before choosing breaks.

For `evidence`, pass an existing relevant file with its real dimensions as `ctx.exampleAsset` (same `path`, `width`, `height` and optional `preserve_region` accepted by `H.addPlannedImage`). Missing assets produce an actionable error; acquire an image or use the explicitly allowed designedPlaceholder example. Its synthetic sample uses a locally drawn lab diagram, not a photo of a real event. The other pages need no external image provider. Text, icons, shapes, connectors and table cells use editable native objects. The optional `pptx-icons.js` library offers more SVG symbols; verify that these render in the target viewer and use native icons when needed.

Adapt colors to categories with consistent contrast; do not recolor arbitrarily just to increase the color count. Panels are useful grouping containers here, not a reason to repeat identical card grids throughout a deck. Keep references alongside the final claims where evidence requires them.

Inspect all complete renders, then the contact sheet. Look for lost details, crowded labels, unintended overlap, excessive headings, isolated giant statements and repetitive layouts. Compare user references for density, imagery and color hierarchy without copying their personal materials.
