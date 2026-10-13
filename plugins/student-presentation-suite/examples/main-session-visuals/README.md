# Main-session visual examples

`pages.js` exports four editable page functions for synthetic teaching content. It can be loaded by the plugin's `auto` page modules; no generated PPTX or images are stored here. See [usage and adaptation](../../skills/sp-deck/references/main-session-visual-examples.md).

These are optional examples of relationships, grouped information, image evidence and problem/action correspondence. The evidence page requires a real asset supplied by the caller. Fonts, colors and geometry are example decisions, not global constraints. Do not use the sample wording as factual evidence for another project.

`rich-pages.js` adds an editable long-title cover, a rich image/table/process page with concise notes, a flat comparison table, and a designed placeholder scene with an `asset_record`. The image examples need caller-supplied `ctx.exampleAsset`; the placeholder works without a provider and must be registered under a confirmed `placeholder_policy: allow`. No binary assets are bundled. Use the cover/template reference for inheritance, not this example's geometry as a required layout.

`photoProcess` combines four supplied image records (`ctx.exampleAssets`, with optional truthful labels) with a native organization process and a highlighted finding. The four images are an example composition, not a deck-wide quota. Preserve actual image context and register the caller's provenance.

`cover` and `shortCover` demonstrate long/short title treatments; their concrete type sizes remain example decisions. Recompose for the actual title, asset and template instead of treating this shared arrangement as a cover engine.
