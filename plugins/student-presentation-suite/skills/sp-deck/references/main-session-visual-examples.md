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

优先从图片证据、图文解释、原生统计图/表格和具体机制图中选择主体。`subject-visuals.js`中的纸张、双人、勾选和气泡只是小型兼容图标，不是丰富主题图解库，不作为默认无图后备。少量用于明确指代即可；调用会登记icon用法并在run汇总跨页复用提醒，不能把同一图标贴满多页来完成视觉要求。

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

### 可见生图提示词占位

`rich-pages.js`导出`promptPlaceholder(ctx, options, box)`，用于用户已经允许的可替换图片区域。options提供prompt、replacement、reason，可选id、kind、label、purpose、labelSize、promptSize；box由当前构图决定。函数返回原生可编辑占位的asset记录，不自动写manifest；调用方将它登记到placeholder_policy: allow的素材清单。prompt完整显示在该区域，供后续生图并替换。不要把提示词缩成读不清的小字；调整区域或提示词表述并看图。此占位明确是待替换图像，不代表已取得照片或成果证据。

## Complete same-material comparisons

`examples/main-session-visuals/cases.json` indexes three full before/after pairs: mechanism, comparable data, and annotated image evidence. `paired-pages.js` uses the same synthetic material on both versions. Read the matching question/learn/avoid entry, then inspect the complete rendered pair when it helps; do not load every example or copy its coordinates. The before versions are deliberate teaching examples, not measured outputs of an earlier model/plugin.

After normal intake approval, or in developer validation, list with `python "${CLAUDE_PLUGIN_ROOT}/scripts/render_visual_cases.py" --list`. Render only the useful pair with `--case mechanism|data|evidence --output-dir <project-output-examples> --render`; output must be outside the marketplace repository. A fresh directory preserves prior evidence. The report identifies fixed-source examples, source asset and rendered pages; it does not grant aesthetic approval. The native chart remains editable; the interface image is a synthetic diagram. Keep example wording and operational labels out of real user slides.

Learn object relationships: the mechanism aligns inputs/actions/retained evidence; comparable data uses a native chart with supported interpretation; image evidence enlarges the actual subject and places markers in unused nearby space. Inspect drawbacks too: long labels may need more room, dense technical material may need another page, and colored rules should not acquire arbitrary meaning. Preserve reference/template constraints and use actual user facts.
