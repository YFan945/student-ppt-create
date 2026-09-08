# Presentation Design Grammar

本文件定义“整套 PPT 如何形成视觉与叙事节奏”，不是固定 layout catalog。

## Core principle

先决定信息角色和视觉节奏，再决定坐标。不要从“这一页套哪个模板”开始。

每套 deck 至少明确：
- `narrative_arc`：opening → context/problem → evidence/method → result → implication → closing
- `visual_motif`：贯穿封面、章节、代表性内容页与结尾的一个克制母题
- `density_rhythm`：高密度页与低密度页交替，避免连续多页相同信息密度
- `composition_rhythm`：不要连续 3 页使用同一构图骨架
- `evidence_rhythm`：事实、图表、案例、结论按论证需要出现，不为“每页有图”凑数

## Page grammar

### Hero / opening
- 1 个核心结论或主题，不堆多个并列模块。
- 可使用大图、巨大数字、短句、强留白。

### Explanation
- 适合“一个结论 + 一个解释结构”。
- 优先使用关系、流程、示意图、annotated visual；若文字本身最有效，可采用 typography。

### Comparison
- 视觉上必须让差异可扫读；至少 2 个对象和明确比较维度。
- 不默认使用等宽卡片，可使用左右对照、矩阵、轴线、before/after、annotated examples。

### Process / architecture
- 结构关系必须可追踪，箭头和层级优先于装饰。
- 节点数量过多时拆页，不通过缩小字号解决。

### Data / evidence
- 一页一个主要图表或一个主要数据结论。
- 图表旁必须放 takeaway；数据来源、单位、范围必须可追溯。

### Typography
- `typography` 是合法的一等视觉策略。
- 适用于关键结论、引用、定义、转折、总结、低密度解释页。
- 通过字号、字重、留白、对齐、少量强调色建立层级；不得为了通过视觉规则硬塞图标或图片。

### Closing
- 收束到一个 takeaway、行动建议或 Q&A cue。
- 不引入新的关键证据。

## Scenario grammar

### Academic / coursework / defense
- 优先论证清晰、图表可信、方法与结果对应。
- 推荐节奏：问题/背景 → 方法 → 关键结果 → 解释/讨论 → 局限 → 结论。
- 少用营销式卡片墙；允许密度较高，但每页只能有一个主要阅读路径。

### Technical / engineering
- 优先架构、数据流、时序、约束与 trade-off。
- 视觉重点放在关系正确性，不追求装饰性插图。

### Business / proposal
- 优先问题、机会、方案、收益、风险、行动。
- 强调关键数字、对比和决策点；避免每页都做 dashboard。

### Teaching / training
- 优先渐进解释、例子、练习、总结。
- 一页只引入有限新概念，必要时拆页。

## Anti-patterns

默认避免：
- 连续多页 2×2 / 3-column 卡片墙；
- 无意义 icon 配额；
- 标题下划线、装饰性色条、无信息价值边框；
- 为“视觉化”把一句简单结论拆成多个小卡片；
- 所有页面视觉重量、背景、构图完全一致；
- 图表没有 takeaway，图片没有解释作用。

## Composition decision

逐页按以下顺序决定：
1. 这页唯一要让观众记住什么？
2. 这是证据、解释、比较、过程、转折还是总结？
3. 最有效的视觉策略是 `data | diagram | image | typography | hybrid` 哪一种？
4. 视觉焦点在哪里？
5. 文字和视觉的比例如何？
6. 与前后页相比，是否形成节奏变化？
7. 再决定具体 bbox、shape、image、chart。

设计系统负责“为什么这样排”，layout/composer 只负责“如何可靠实现”。
