# Image And Visual Strategy

## New-task policy (2.1)

For new tasks, [model-led-design.md](model-led-design.md) owns design modes, frozen semantic
requirements and measured text. Its policy overrides legacy template/scale/
verbatim-copy guidance below. `auto` is the default; user brand/template/logo
and actual readability remain binding. Treat fixed sizes, proportions and
gallery treatments here as optional design suggestions for new tasks.


Use this strategy across planning, optional Art Direction, production, and review. Choose available assets and information-bearing graphics before composition; visual richness comes from relevant evidence, explanatory imagery, readable tables/charts and meaningful diagrams, with icons as optional auxiliary labels.

## Source Choice

- Use user-provided assets first when they are relevant, clear, and allowed.
- For real people, places, products, historical material, current events, factual charts, and source-sensitive examples, resolve existing web authorization before acquiring images. Ask only when the needed authorization is absent; do not ask again when already allowed.
- For abstract concepts, process explanations, cover mood images, and conceptual scenes, generated visuals may be used when the current environment provides approved generation and the user does not forbid it.
- If the user says no network, no generated images, or user-assets only, respect that constraint and use diagrams, native charts, custom SVG, built-in semantic icons, or typography-led layouts.

## Visual mix

Before writing pages, choose the expression that each page needs. Art Direction remains optional. Useful choices include:

- Relevant images for cover, opening or closing;
- Evidence visuals such as screenshots, research figures, photos or annotated diagrams;
- Native charts when quantitative evidence supports a comparison;
- Editable diagrams, process paths, timelines, tables and category groups;
- Typography-led pages when a clear statement genuinely carries the page.

Use deliberate diversity of information-bearing visuals. Prefer meaningful images, editable tables/charts and detailed diagrams over repeated small icons. Do not impose asset quotas. `diagram-only` permits detailed multicolor diagrams and native charts/tables; it does not mean plain text plus a few lines. No external provider configuration means external acquisition is unavailable, not that user files or native drawing tools are unavailable. An old demonstration's diagram-only setting is not the default for the next task. For new mixed-visual tasks record the authorized hybrid-adaptive policy; do not silently turn missing configuration into a user ban on images or approved placeholders.

For each slide, classify the desired asset before layout:

```text
hero image | evidence image | annotated screenshot | native chart | diagram/process
| comparison/matrix | typography | none-needed
```

Actively use available authorized tools for topical imagery; keep accurate tables, charts and diagrams editable. If the intended asset is unavailable, use another suitable asset or an explicitly allowed designed placeholder with a clear replacement target. Do not silently replace a hero visual with four empty cards. A placeholder is a deliberate visual treatment, not an unfinished page; see `image-sourcing.md` for policy and provenance.

Semantic icons are auxiliary labels, navigation or legends; they do not by themselves fulfill the primary visual plan. For numeric material, select comparisons, trends, distributions or an evidence table from actual units, dates, denominators and relationships. Independent counts with different units need not share a chart axis; do not invent a funnel, percentage, baseline or missing observations to satisfy a request for charts. A labeled chart/table skeleton is possible only under an allowed placeholder policy.

When an image slot is approved but the image is not yet obtainable, preserve a meaningful image region and show a usable generation prompt there when requested: subject, setting/action, visual style, composition/crop, palette and text-free/accuracy constraints. Keep this instruction inside the placeholder; it is removed with the slot when the final image arrives. The image-sourcing owner defines its record and validation.

## Deterministic Internal Visual Stack

The plugin already has an editable/no-network visual stack:

- `scripts/pptx-visuals.js` for process, comparison, timeline, architecture and structured native visuals;
- native PptxGenJS charts and editable tables for quantitative evidence;
- custom SVG/native shapes for content-specific diagrams and explanatory illustrations;
- `scripts/pptx-icons.js` for auxiliary semantic icons;
- `scripts/pptx-svg-library.js` for optional motifs/background references.

Choose icons, diagrams, charts, photographs and evidence figures according to the information they communicate.

## Image Sourcing Capability

搜图/生图是否为可用能力，由项目根目录的 `image-sources.json` **显式声明**，不靠假设。运行
`check_claude_pptx_env.py` 会报告 `capabilities.image_search_ready` /
`image_generation_ready` / `user_assets_ready`；未声明时全部为 `false`。

`ready` 仅表示配置条件满足；实际获取结果及过期判定见 `image-sourcing.md`，不能据环境声明承诺已获得图片。

- 声明格式、权限门禁、来源留痕与降级顺序见 `image-sourcing.md`（schema：`image-sources.schema.json`，示例：`image-sources.example.json`）。
- 规划顺序应为"先解析能力，再决定 asset plan"，不要先画好版式再发现拿不到图。
- 每张外部/生成图都要写入 `asset-manifest.json` 的来源字段（`source_url`、`license`、`provider_id`、`retrieved_at`、`prompt`），并用 `pptx_tool.py validate-asset-manifest` 校验。

## Optional External Image Generation

插件不内置或承诺特定生图服务。只有 `image-sources.json` 声明了可用的 `image-generation`
provider 且用户未拒绝时，才可为封面、背景或抽象概念制作关键插图；能力不可用、用户拒绝或成本
不合适时，使用 deterministic visual stack，不把生图当硬依赖。

- 适用：cover/closing hero、抽象概念、氛围性但内容相关的主视觉。
- 不适用：图表、流程图、架构、需要准确文字/数字的 evidence visual。
- prompt 为幻灯片文字留出明确空间；从当前页面设计选定 palette、crop language 和 treatment，已有可选 `art-direction.yaml` 时才参考该文件，用户指定的品牌与保留项必须遵守。旧任务继续遵循其冻结的视觉要求。
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

An approved designed placeholder may preserve the intended image region: use a topical illustration, schematic or replaceable photo/screenshot treatment with a readable label. Mark potentially misleading images as “示意图” or “素材待替换”; keep the replacement list in working records/delivery. Missing data permits a labeled table/chart skeleton, not invented values, bars or trends. Explicit user prohibitions and old frozen controls remain effective.

- causal/process flow;
- comparison or decision matrix;
- timeline/path;
- architecture/concept diagram;
- native data chart;
- annotated text/quote evidence;
- axis/quadrant/trade-off map;
- oversized typographic thesis;
- semantic icons or icon-based information graphics.

## Production Notes

- Images should explain, evidence, or frame the slide's main message.
- A visual must have an explicit role in the authored page; avoid “put something on the right because the left has text.” No composition-candidate file is required.
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
- visual treatment that fails to communicate the planned information;
- a deck whose asset mix is technically valid but monotonously text/shape-heavy.
