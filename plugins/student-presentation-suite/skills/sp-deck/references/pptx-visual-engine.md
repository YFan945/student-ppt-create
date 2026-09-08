# PPTX Visual Engine

本文件定义 suite-owned 的视觉辅助与安全契约。风格和版式是创作建议，不是逐页固定模板；
只有内容真实性、可读性、来源、容量、边界、文字适配、实际元素安全和完整 QA 是硬约束。

## Adaptive-freeform by default

Create/rebuild 默认由模型根据页面任务、素材和叙事节奏编写完整 `deck.js`。先加载
`pptx-design-grammar.md`，确定整套 deck 的 design grammar，再分析单页任务；随后从
`pptx-layouts.js` 获得 2–3 个可行构图建议。可以移动、缩放、合并、拆分区域，改变比例、
形状和图片裁切，也可以完全采用更合适的原创构图。

`pptx-composer.js` 是安全辅助层和兼容入口：

- `suggestCompositions()`：返回 2–3 个灵感候选，不返回最终坐标。
- `resolveSlideComposition()`：默认返回 `adaptive-freeform` 建议；仅 `layout_lock: true`
  或 `deterministic-fallback` 解析精确版式。
- `preflightSlide()`：保留为 composition-level 的早期检查，不再被视为最终几何安全证明。
- `renderSlide()` / `renderDeck()`：保留给锁定版式和确定性 fallback。

`composer_deck.js` 只作为旧项目和自由构图失败后的确定性 fallback，不是 create/rebuild
默认入口。手写 `deck.js` 可以自由构图，但不能绕开 Actual Element Registry、来源检查和 QA。

## Actual Element Registry — default hard preflight

自由构图时，**真正送入 PptxGenJS 的实际元素**必须登记到
`${CLAUDE_PLUGIN_ROOT}/scripts/pptx-element-registry.js`。检查对象必须与最终渲染对象一致，而不是只检查
一个 advisory composition plan。

推荐 generator 模式：

```js
const { SlideElementRegistry } = require(`${process.env.CLAUDE_PLUGIN_ROOT}/scripts/pptx-element-registry.js`);
const registry = new SlideElementRegistry({ slideW: 13.333, slideH: 7.5 });

// 每次 addText/addShape/addImage/addChart/addLine 时，同时登记真实 bbox / 文字属性。
slide.addText(title, titleOpts);
registry.text(slideNo, title, { ...titleOpts, fontSize: 38 });

slide.addImage(imageOpts);
registry.image(slideNo, imageOpts);

// 所有页面完成后，在 writeFile 前阻断实际几何错误。
const geometryReport = registry.assertSafe();
```

默认静态检查至少覆盖：

- 非法/负尺寸 bbox；
- 元素越界；
- text↔text、text↔image/chart/shape 的明显实际重叠；
- line 穿过文字的可疑情况；
- CJK/Latin 混排下的保守文字高度估算；
- 所有检查结果均来自实际注册对象。

装饰背景、刻意叠加或图表内部标注可以使用 `decorative: true` / `allowOverlap: true` 等显式豁免；
禁止通过全局关闭检查来消除 blocker。Registry 不替代最终 render，它负责“别画坏”，Render Critic
负责“画得是否好看”。

## Composition and shapes

`pptx-layouts.js` 保留 36 个 ID 作为 inspiration catalog，并记录：
`composition`、`shape_slots`、`text_policy`、`asset_slots`、`corner_decoration`、
`variant_fallbacks`。normalized zones 是比例参考，允许调整。只有用户明确锁定、模板复现或
自由构图失败时才用 `resolveLayout()`。注册表由 `layout-library.schema.json` 校验。

`pptx-shapes.js` 支持 `rect`、`roundRect`、`ellipse`、`pill`、`hexagon`、
`chevron`、`parallelogram`、`arch`、`bracket` 和 `none`。正文安全区必须通过
`safeInsetForShape()` 计算，不能把文字放进尖角。非矩形用于有语义的节点、比较、路径、
焦点和图片框；正文阅读区仍优先使用平面排版。

## SVG library

`pptx-svg-library.js` 提供 `getCornerSvg()`、`getPatternSvg()`、
`addCornerDecoration()`。12 套正式 SVG 参考包括 bracket、crop-mark、slash、arc、tape、axis、
contour、beam、focus、circuit、checkpoint、stamp。SVG 只承担角饰、背景纹理和确定性辅助插图；
AI 可调用、组合、修改或完全不用，系统不得自动添加视觉配额。正文、数据和主要结构保持 PowerPoint 可编辑。

## Text fit and alignment

使用 `fitText()`、`preflightText()` 和 `addFittedText()` 做早期适配；最终实际文本仍须登记进
Actual Element Registry，再由 render QA 验证真实字体/换行结果。

- card、node、KPI、短标签：水平居中 + 垂直居中。
- title：按版式左对齐或居中，垂直居中。
- body、list、reference：左对齐；短内容垂直平衡，长内容顶部对齐。
- quote focus 可居中；quote analysis 左对齐。
- caption/source 独立使用 10–12pt，不被正文下限抬高。

无法在角色硬下限内适配时必须阻断，按“扩大区域 → 换变体 → 换版式 → 压缩文案 → 拆页”解决；
禁止只告警后交付。

## Design grammar above style/layout

视觉风格只负责 palette、typography character、background 和 motif；整套页面语言由
`pptx-design-grammar.md` 决定。create/rebuild 默认必须根据 presentation type 选择一个 grammar。

Design grammar 决定：

- deck 的叙事节奏；
- 哪些页面适合大图、大数字、结构图、数据图、文字主导；
- 页面之间如何避免连续同构；
- 什么是合法的 `visual_strategy`；
- 场景级 anti-pattern。

`visual_strategy: typography` 是正式的一等策略。高质量文字主导页不需要为满足“视觉配额”强塞图标、
卡片或图片。

## Lightweight visual reference

resolved tokens 只提供 `style_character`、六角色 `palette`、四类 `backgrounds` 和一个
`svg_reference`。它们不参与版式排序，也不指定形状、图片处理、图表语法、组件或页面节奏。
`Other` 使用同一结构，并在 Production Summary 中完整展示后确认。SVG 不自动插入；只有模型
判断它能支持页面任务时才显式调用。

## Assets

默认 `hybrid-adaptive`：优先可靠用户素材；缺图时使用原创 SVG、原生图表、关系图、时间线或形状结构。
禁止空图片框、装饰性 placeholder 和 filler icon。普通任务直接在 Slide Spec 或生成脚本中保留素材来源与
alt text。只有外部素材许可需要归档、高风险模板编辑或用户明确要求审计证据时，才生成并验证
`<topic>-asset-manifest.json`。
