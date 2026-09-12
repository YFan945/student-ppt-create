# Image And Visual Strategy

Use this shared strategy across planning, Art Direction, PPTX production, and review. v0.8 treats visual richness as an **asset-planning problem**, not something to patch at the end after a text-heavy deck already exists.

## Source Choice

- Use user-provided assets first when they are relevant, clear, and allowed.
- For real people, places, products, historical material, current events, factual charts, and source-sensitive examples, ask whether web search is allowed before using web images.
- For abstract concepts, process explanations, cover mood images, and conceptual scenes, generated visuals may be used when the current environment provides approved generation and the user does not forbid it.
- If the user says no network, no generated images, or user-assets only, respect that constraint and use diagrams, native charts, custom SVG, built-in semantic icons, or typography-led layouts.

## v0.8 Asset Plan

After Slide Spec freeze, `art-direction.yaml` must decide the deck's visual mix before final composition. For a typical 8–10 slide high-score deck, a useful starting mix may be:

- 1–2 hero/concept visuals for cover, hook or closing;
- 2–3 evidence visuals such as screenshots, research figures, real photos or sourced diagrams;
- 1–2 native charts when quantitative evidence exists;
- 1–2 editable diagrams/process/architecture visuals;
- 1 intentionally typography-led slide when content supports a strong thesis.

These are not quotas. The requirement is **deliberate diversity of information-bearing visuals** so the generator does not fall back to rectangles and text on every slide.

For each slide, classify the desired asset before layout:

```text
hero image | evidence image | annotated screenshot | native chart | diagram/process
| comparison/matrix | semantic icon | typography | none-needed
```

If the intended asset is unavailable, change the visual strategy or reference recipe before writing the final page; do not leave a placeholder and do not silently replace a hero visual with four cards.

## Deterministic Internal Visual Stack

The plugin already has an editable/no-network visual stack:

1. `scripts/pptx-visuals.js` for process, comparison, timeline, architecture and structured native visuals;
2. `scripts/pptx-icons.js` for small unified line icons used as semantic accents;
3. `scripts/pptx-svg-library.js` for motifs/background references;
4. native PptxGenJS charts for quantitative evidence;
5. custom SVG/native shapes for topic-specific diagrams.

Use semantic icons sparingly: navigation, state, risk, user/system roles, small concept labels. Icons are not a substitute for a real diagram, chart, screenshot or evidence figure. A slide with four icons above four equal boxes is still a card grid.

## Image Sourcing Capability

搜图/生图是否为可用能力，由项目根目录的 `image-sources.json` **显式声明**，不靠假设。运行
`check_claude_pptx_env.py` 会报告 `capabilities.image_search_ready` /
`image_generation_ready` / `user_assets_ready`；未声明时全部为 `false`。

- 声明格式、权限门禁、来源留痕与降级顺序见 `image-sourcing.md`（schema：`image-sources.schema.json`，示例：`image-sources.example.json`）。
- 规划顺序应为"先解析能力，再决定 asset plan"，不要先画好版式再发现拿不到图。
- 每张外部/生成图都要写入 `asset-manifest.json` 的来源字段（`source_url`、`license`、`provider_id`、`retrieved_at`、`prompt`），并用 `pptx_tool.py validate-asset-manifest` 校验。

## Optional External Image Generation

插件不内置或承诺特定生图服务。只有 `image-sources.json` 声明了可用的 `image-generation`
provider 且用户未拒绝时，才可为封面、背景或抽象概念制作关键插图；能力不可用、用户拒绝或成本
不合适时，使用 deterministic visual stack，不把生图当硬依赖。

- 适用：cover/closing hero、抽象概念、氛围性但内容相关的主视觉。
- 不适用：图表、流程图、架构、需要准确文字/数字的 evidence visual。
- prompt 必须为幻灯片文字留出明确空间，并遵循 `art-direction.yaml` 的 palette、crop language 和 treatment。
- 生成后逐图检查构图、错字、裁切和事实暗示，不把生成画面当事实证据。

## Sourced Web Images

仅当 `image-sources.json` 中 `web-search` provider 可用且用户已授权联网时，real-world subjects
优先来源明确的高质量图片，而不是搜索结果里第一张小图。记录来源 URL；必要时保留作者/机构/日期。优先选能支撑 slide claim 的图片，例如真实界面、研究图、人物/地点证据，而不是抽象 stock photo。

图片进入 composition 前就决定 crop language：

- **full-bleed**：视觉即叙事，文字很少；
- **half-bleed**：一侧强视觉 + 一侧文本；
- **edge crop**：视觉越出常规内容框，制造更强编辑感；
- **inset figure**：学术/数据证据，保留 caption/source；
- **annotated screenshot**：大图 + 2–4 个精准标注。

优先一个有决定性的 crop，不要用多个小型 floating stock images 伪造“丰富”。

## Fallbacks

If no suitable image is available, prefer an information-bearing transformation rather than unrelated decoration:

- causal/process flow;
- comparison or decision matrix;
- timeline/path;
- architecture/concept diagram;
- native data chart;
- annotated text/quote evidence;
- axis/quadrant/trade-off map;
- oversized typographic thesis;
- semantic icon only as a small supporting cue.

## Production Notes

- Images should explain, evidence, or frame the slide's main message.
- A visual must have an explicit role in the composition candidate; avoid “put something on the right because the left has text.”
- Text over images needs robust contrast through crop choice, negative space, or a purposeful opaque/translucent panel.
- Preserve aspect ratio unless an intentional crop is specified.
- Record web image/source URLs in speaker notes or references when appropriate.

## Review Notes

When reviewing an existing deck, flag:

- unclear source or copyright risk;
- low-resolution, stretched, badly cropped or unreadable screenshots;
- visuals that do not support the argument;
- factual visuals without citation;
- busy backgrounds that reduce readability;
- pages that claim `visual-led` but only contain decorative icons/cards;
- a deck whose asset mix is technically valid but monotonously text/shape-heavy.
