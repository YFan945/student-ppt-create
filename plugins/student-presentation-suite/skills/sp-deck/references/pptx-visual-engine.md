# PPTX Visual Engine

本文件定义 suite-owned 的视觉生成与安全辅助。v0.8 仍保留 `adaptive-freeform`，但不再让模型面对空白画布只靠抽象文字规则直接写坐标。最终自由构图必须建立在 **Art Direction + Visual Reference Retrieval +（高价值页）Multi-candidate Wireframe Selection** 之上。

## v0.8 hierarchy of visual decisions

```text
Style Seed
  → Design Grammar
  → Art Direction
  → Visual Reference Recipes
  → Composition Candidates / Wireframes
  → Final PptxGenJS elements
  → Actual Element Registry
```

每层职责不同：

- style seed：用户可理解的气质、palette、背景起点；
- design grammar：场景的叙事动作与页面语言；
- Art Direction：字体尺度、图片裁切、图标/图表/组件语言、motif、背景节奏、asset mix；
- reference recipe：具体的正向构图先验与 `why_it_works`；
- candidate：当前页可比较的 2–3 个视觉解法；
- final elements：最终真实可编辑 PPT 对象。

不要把这些层合并回“一份很长的 prompt → 直接 deck.js”。

## Adaptive-freeform, but reference-first

Create/rebuild 默认仍由模型编写完整 `deck.js`，可以自由移动、缩放、合并、拆分区域，改变比例、形状和图片裁切，也可以明显偏离 reference recipe；但最终构图必须能解释它如何服务 slide claim、Art Direction 与选定/检索到的 positive prior。

`pptx-composer.js` 保留为辅助层：

- `suggestCompositions()`：返回局部构图灵感；
- `resolveSlideComposition()`：默认只给 `adaptive-freeform` 建议；`layout_lock: true` 或 deterministic fallback 才解析精确版式；
- `preflightSlide()`：composition-level safety preflight，不是最终几何证明；
- `renderSlide()` / `renderDeck()`：锁定版式和 deterministic fallback。

`composer_deck.js` 只用于兼容和自由构图失败后的 fallback，不是 create/rebuild 默认入口。

## Positive visual priors

v0.8 的目标不是增加更多“禁止项”，而是让模型在写坐标前拿到可执行的正向设计动作。

### Typography hierarchy

Art Direction 必须给出明确 type scale。推荐范围：cover 44–60pt、普通标题 30–38pt、key statement 28–42pt、中文 body 17–22pt、英文 body 16–20pt、caption/source 9–12pt。实际字体可因可读性/环境调整，但普通标题与正文的感知层级通常至少约 1.45×。

这不是允许无限缩小正文：若教室距离、用户 rubric 或内容复杂度要求更大字体，优先删减/拆页。旧 hard minimum 只作为安全 guard，不应把所有页面推成“24pt 标题 + 22pt 正文”的弱层级。

### Image treatment

图片不只是“有/没有”。Art Direction 必须指定主要 crop language：full-bleed、half-bleed、edge crop、inset figure、annotated screenshot 等。优先一张决定性的主视觉，而不是多个小型无关 stock image。图片 overlay 文本必须设计对比层，不用无语义渐变遮罩掩盖裁切问题。

### Chart grammar

原生 chart 是可编辑 evidence visual，但不能使用 PowerPoint/PptxGenJS 默认样式直接交付。通常突出一个 series / number，弱化 gridlines/frame，优先 direct labels，保留 source/caption，并让 takeaway 先于图表细节被读到。

### Components

cards、pill、icon circle、border、shadow 都是组件，不是页面语法。默认先用 alignment、scale、whitespace、image/figure 和 type hierarchy 建立结构。只有内容真的需要分组、状态、并列实体时才使用 card；“有 N 项 → N 个等宽矩形”不是默认映射。

## Visual Reference Library

`visual-reference-library.json` 是 v0.8 的 curated positive-prior catalog。每项包含：

- narrative roles / grammars / visual strategies；
- density / tags / silhouette；
- `why_it_works`；
- dominant element / focal share；
- normalized wireframe；
- adaptation notes。

`visual_reference_select.py` 根据当前 slide task 与最近视觉历史返回 2–3 个不同 silhouette。reference 不提供事实内容，也不要求像素级复制；它的价值是让模型“先看到一个成功的构图逻辑”，避免空白画布生成。

36 个 `pptx-layouts.js` ID 继续保留，记录 `composition`、`shape_slots`、`text_policy`、`asset_slots`、`corner_decoration` 和 fallbacks，但其优先级低于 visual reference recipes。normalized zones 仍可用于 deterministic fallback。

## Multi-candidate wireframe exploration

对 cover / hook / central mechanism / strongest evidence / closing 等 high-leverage 页：

1. 从 reference retrieval 得到多个 positive priors；
2. 模型产生 2–3 个真正不同 silhouette 的 candidate；
3. `composition_candidate_check.py` 检查 focal ownership、type hierarchy、reference provenance、normalized zones 和候选差异；
4. `composition_wireframe.js` 生成低成本 PPTX；
5. render wireframes，模型直接观察视觉重量/留白/结构；
6. 记录 `selected_id` + `selection_reason` 后才写 final elements。

候选 wireframe 不是成品 slide，也不受最终 aesthetic QA 取代。其目的在于**在昂贵的正式生产之前扩大设计搜索空间**。

## Actual Element Registry — hard preflight

最终自由构图时，真正送入 PptxGenJS 的实际元素必须登记到 `${CLAUDE_PLUGIN_ROOT}/scripts/pptx-element-registry.js`。检查对象必须与最终渲染对象一致，而不是 advisory plan。

```js
const { SlideElementRegistry } = require(`${process.env.CLAUDE_PLUGIN_ROOT}/scripts/pptx-element-registry.js`);
const registry = new SlideElementRegistry({ slideW: H.SLIDE_W_IN, slideH: H.SLIDE_H_IN }); // 10 × 5.625in，与 applyTokens 的 STUDENT_WIDE 版式一致
slide.addText(title, titleOpts);
registry.text(slideNo, title, { ...titleOpts, fontSize: 34 });
slide.addImage(imageOpts);
registry.image(slideNo, imageOpts);
const geometryReport = registry.assertSafe();
```

默认静态检查覆盖非法/负尺寸 bbox、越界、明显 text↔text / text↔visual 重叠、line 穿文字、保守文字高度估算等。装饰背景、刻意叠加可用显式 `decorative` / `allowOverlap` 豁免；禁止全局关闭检查。Registry 负责“别画坏”，不负责决定“什么最好看”。

## Shapes, SVG and icons

`pptx-shapes.js` 支持 rect/roundRect/ellipse/pill/hexagon/chevron/parallelogram/arch/bracket 等；非矩形用于有语义的节点、路径、焦点和图片框，正文阅读区优先平面排版。

`pptx-svg-library.js` 的 bracket/crop-mark/slash/arc/tape/axis/contour/beam/focus/circuit/checkpoint/stamp 是 motif/背景辅助，不是内容视觉配额。`pptx-icons.js` 提供统一线性语义 icon；用于导航、状态、小型概念标记，不替代 chart/diagram/evidence image。

## Assets

默认 `hybrid-adaptive`，但 v0.8 要在 Art Direction 里提前写 asset plan。优先级：

1. 用户提供且可靠的真实图/截图/研究 figure；
2. 获准的 sourced web visual（人物、地点、产品、历史/当前事实等）；
3. 可用且获准的 conceptual image generation；
4. 原生 chart、diagram、timeline、architecture、custom SVG；
5. `pptx-icons.js` 的小型 semantic icon；
6. typography-led visual。

不要把“没找到图”自动降级为一页矩形卡片；关系、流程、比较、坐标、数据和 typographic thesis 都是更强的 deterministic visuals。

## Text fit and alignment

继续使用 `fitText()`、`preflightText()`、`addFittedText()` 做早期适配；最终真实文本仍登记 Registry，并由 render QA 验证字体/换行。无法在 Art Direction 目标层级与硬可读下限内适配时，按“删减 → 扩大区域 → 换 candidate/reference → 拆页”解决，不要先缩字体。

## Design quality loop

v0.7.1 的 render-conditioned QA 继续保留，但 v0.8 增加一条原则：如果 render 没有工程 bug、却视觉平庸，应优先判断是否 **Art Direction 太弱 / reference 选错 / candidate 搜索不足**，而不是只对现有坐标做 5% 的微调。生成器与 critic 的职责要尽量分离；能使用独立 review context/subagent 时，优先让非作者观察 render。
