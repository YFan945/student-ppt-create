# PPTX Design Grammar

本文件位于 visual style 与 layout inspiration 之上：**style 决定视觉气质，design grammar 决定整套
PPT 如何用页面语法表达内容，layout 只提供局部构图参考。** 默认 create/rebuild 必须先选一个 grammar，
再逐页决定具体 composition；不得用固定 layout 配额代替设计判断。

## Core principles

1. 先决定叙事动作，再决定页面构图：`introduce / frame / explain / compare / prove / synthesize / conclude`。
2. 同一 deck 需要视觉节奏：大图/大数字/结构图/文字主导/数据页交替，避免连续 3 页同构。
3. 视觉元素必须承担信息功能。没有合适图片时宁可使用 typography、原生图表、关系结构或留白，禁止 filler icon/card。
4. 每页只允许一个 primary focal point；次要元素围绕焦点建立层级。
5. `pptx-layouts.js` 的 36 个 layout 是 inspiration catalog，不是页面类型枚举，也不是模板配额。
6. 允许高质量 text-led slide。`visual_strategy: typography` 是合法结构化视觉策略，不得因 high-score 模式强制塞图。

## Grammar families

### Academic research

适用于课程研究、论文汇报、实验报告、学术答辩。

- Opening：问题/研究对象优先，不以目录卡片作为视觉高潮。
- Method：流程、框架、实验设置优先用原生结构图或关键步骤序列。
- Evidence：结果先于解释；数据页突出一个 takeaway，并保留来源/单位/范围。
- Discussion：限制、trade-off、failure case 可以使用对照、矩阵或 annotated visual。
- Rhythm：`question → method → evidence → interpretation → implication`，避免背景连续占据多页。
- Preferred motifs：坐标轴、标注线、细分隔、crop mark、figure-caption 语法。

### Technical engineering

适用于软件工程、系统设计、架构、算法、技术方案。

- Architecture：先展示 system boundary，再展示 component/data flow；一页不要同时塞完整架构和实现细节。
- Process：优先 flow/path/state，而不是等宽卡片。
- Comparison：强调 trade-off 和 decision criteria，而不是简单功能罗列。
- Code/metrics：代码只保留关键片段；性能数据使用原生 chart + takeaway。
- Rhythm：`problem → architecture → mechanism → evidence → risk → decision`。
- Preferred motifs：circuit/axis/beam、直角连接线、网格与模块边界。

### Coursework / teaching

适用于课堂汇报、课程展示、知识讲解。

- 每页只回答一个问题或传达一个知识结论。
- 概念解释优先 `definition → intuition → example`；复杂过程优先分步揭示。
- 文字主导页使用大字号、关键字强调和清晰留白，而不是为了“丰富”堆卡片。
- Rhythm：`hook → concept → example → application → recap`。

### Defense / competition

适用于答辩、竞赛、项目路演。

- 封面后快速建立“为什么值得听”；问题、创新、成果提前。
- Innovation 页必须突出差异点与证据，不使用均匀三卡片弱化主次。
- Result 页优先巨大数字、before/after、真实截图或实验图。
- Ending 页回收 opening 的核心 promise，并明确 contribution / next step。
- Rhythm：高对比、短句、强 focal point，避免连续密集说明页。

### Business / proposal

适用于商业提案、决策、运营汇报。

- 结论先行；每页标题尽量是 action title。
- 数据页以 decision takeaway 为主，图表为证据。
- 方案页强调选择、成本、收益、风险，不做功能清单堆积。
- Rhythm：`context → insight → choice → impact → ask`。

### Brand / creative showcase

适用于品牌、作品集、视觉展示。

- 图片与排版承担主要叙事；文字显著减量。
- 可以更强地使用 full-bleed、非对称、crop、oversized type，但仍遵守边界与可读性。
- 保持一个持续 motif，不要每页随机换视觉语言。

## Per-slide composition contract

模型在写实际 PptxGenJS 前，先为每页确定以下最小 contract（可以内联在 generator，不强制另存文件）：

```yaml
role: prove
visual_strategy: chart        # typography | image | chart | diagram | comparison | process | table | mixed
focal_point: "主结果 23.4%"
hierarchy:
  primary: takeaway
  secondary: chart
  tertiary: source
composition_intent: "左侧结论，右侧图表；结论占视觉权重约 40%"
reference_layouts: [data-focus, split-proof]
allow_freeform: true
```

`reference_layouts` 只用于启发。真正的硬约束由 Actual Element Registry、文字适配、package validation、
artifact readback 与 render-conditioned visual review 负责。

## Anti-patterns

- 连续三页以上相同的 hero/card/three-column 结构。
- 为满足“每页有视觉”强塞图标、emoji、装饰图、无关照片。
- 2×2/3×1 卡片成为默认页面语法。
- 所有元素视觉权重相近，缺少 focal point。
- 标题下划线、装饰性色条、无语义渐变、玻璃拟态作为默认风格。
- 为避免溢出而把正文缩到硬字号下限以下。
