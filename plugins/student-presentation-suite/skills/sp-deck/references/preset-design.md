# Preset design and assets

A visual style and a design mode are independent: selecting Academic Rigorous or Creative Student still permits `auto`. A preset supplies usable colors, fonts and optional background treatment; it does not prescribe content density or image counts. Every selected style should support a complete student presentation with useful evidence, readable detail and variation.

Use `H.categoryColors(tokens, optionalColors)` for consistent category/series encoding. Component `colors` and page typography can override these defaults. Built-in background treatment is available through `H.renderBackground`; set `decorations: false` when imagery, a template or the composition calls for a plain field. Extra colors are available, not required on every page.

Corner motifs are optional and enabled with `motif: true` when they fit the composition.

## Match expression to the material

- Academic / data: annotated evidence figures, multi-result charts, method diagrams and comparisons with supporting detail.
- Business / technology: system screenshots, architecture relationships, product/user flows and results linked to actions.
- Creative / humanistic: user-supplied documentary photos, project/process imagery, quotations and grouped observations.

Choose from the actual material. Inspect provided images and screenshots before planning an image region. Use available authorized search/generation only when it serves the subject; if unavailable, use meaningful native diagrams, tables, charts and icons. Selecting a preset does not authorize external services or manufacture evidence.

## Runnable references

`examples/main-session-visuals/pages.js` contains native relationship, grouped information, annotated image and problem/action pages whose colors follow the selected preset. `scripts/style_preview_deck.js` builds a two-page synthetic information/evidence preview, not a real result claim. They are optional examples; adapt content and layout.

Tables can use a colored header, meaningful row/column emphasis, subtle banding, aligned numbers and spacing instead of dense full-cell grids. Preserve user/template formatting. Use `V.addStyledTable` or editable `addTable` cells; choose typography and column widths from the content.

For `guided`, use declarative page data rather than copying a free-page function. For example, a results table can use:

```javascript
module.exports = {
  kind: 'content', move: 'proof',
  slots: { title: '课程观察', claim: '把记录与下一步行动对应起来',
    visual: { type: 'table', details: {
      columns: ['观察', '记录数量', '下一步'],
      rows: [['资料整理', 18, '核对来源'], ['协作记录', 16, '完善分工']],
      font_size: 14, header_font_size: 15
    }}},
  notes: '资料整理与协作记录分别对应来源核对和分工完善。'
};
```

These numbers are example data. Replace them with your own evidence and keep the public-facing wording substantive under shared standards.

View every full page and compare supplied references. Check whether supporting detail survived, photos/diagrams explain the subject, categories remain distinguishable, reading order is clear, and page rhythm fits the style. Repair and re-render; technical `ok` is not aesthetic approval.
