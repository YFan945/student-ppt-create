# Structured Render Visual Critic

v0.7.1 把视觉复核从“有没有溢出/重叠”升级为真实页面设计审查；v0.8 进一步要求 critic 判断**最终 render 是否兑现了 Art Direction、reference/candidate 的设计意图，以及生成阶段是否因为过度保守而丢掉视觉张力**。本文件定义查看真实 render 后必须写出的 `visual-review.json`。

## 核心原则

1. 先看真实 render，再写报告；不得根据 Slide Spec、deck.js、candidate JSON 或自我想象代替看图。
2. `没有 overflow/overlap` 只代表工程可用，不代表设计优秀。
3. High-score deck 的 Major/Critical 视觉问题必须 repair，不能只记录后 complete。
4. 视觉问题优先修 actual artifact；不要为了过检查反向修改 frozen Slide Spec。
5. 必须检查整套节奏：连续弱卡片/列表/三等分属于 AI-template repetition 风险。
6. **Author/critic separation**：Pipeline 必须由主会话以不传 `name` 的方式独立 spawn `student-presentation-suite:visual-critic`。独立 critic 使用 Read 读取当前 contact sheet 和全部页图，并用 Write 写 visual-review.json；hook 生成 critic-execution.json。无法分离时必须 blocked，不能用生成者自评分替代。
7. v0.8 critic 不只是给分：如果最终页明显弱于选定 wireframe/reference 的视觉命题，应指出是哪一步退化（asset、hierarchy、crop、composition、type scale 或实现保守化）。
8. **配色一致性**：整套只能使用所选风格的两套 palette（light `palette` + 对应 `dark_palette`）。
   深色封面/章节/收尾页必须来自 `dark_palette`，不能是生成时临时挑的深色；发现任何 palette
   之外的强调色或底色、或直接写死的 hex，按 `art-direction` / `implementation` 返修。

## blocker 口径必须与质量门一致

`rigorous` 的 blocker = `critical` + `major`。`fast` 的主观视觉分数、重复版式和
`major` 风格意见只作 advisory；只有无法使用的页面（例如文字无法辨认）报 `critical` 并
阻塞。Critic 应把 `fast` 档的风格建议写成 `minor`，`blocker_count` 与回给主会话的计数按
当前质量档计算。QA 保留这些建议，但不会因此要求 Builder 反复改版。

2026-09-17 live：critic 按自己的习惯回报"blocker 数：0（critical 0 / major 8 / minor 12）"，
主会话据此判断"独立复核已判定可交付"，而质量门同一份报告算出 23 个 blocker。现在必须
先读质量档，再按该档统一汇总口径。

## visual-review.json

形状的**唯一 canonical 来源是 `references/visual-review.schema.json`**（本示例与它逐字段一致）。
2026-09-17 live 教训：critic 首轮按一份过时示例的记忆交了 `issues` 顶层结构，QA 门只回了派生
错误（“must contain a slides array”），主会话此后每次 spawn 手贴完整 schema 四次。
不要再凭记忆写形状；不确定时读 schema 文件。

注意 schema 的 `required` 只含 QA 门真正消费的最小集（`pptx_sha256`、`slides`；每页
`slide`/`visual_structure`/`scores`/`issues`）——本示例演示的是**推荐完整形状**，多写不罚、
少写必需字段会被 QA 判 `visual_review_schema_invalid`，报错会直接点名缺哪个字段。
`verdict`/`severity_counts`/`overall_summary` 这类汇总字段门不读，但值得写：它们是人读尸检
的入口，也是 repair 轮次判断的摘要。未知字段只报 `visual_review_schema_extra`（minor，不阻塞）。

```json
{
  "review_version": "2.0",
  "work_id": "<work-id>",
  "pptx_sha256": "<current pptx sha256>",
  "contact_sheet_sha256": "<manifest.render.contact_sheet.sha256>",
  "page_sha256": {"1": "<manifest.render.pages[0].sha256>"},
  "page_count": 1,
  "verdict": "pass_with_issues",
  "blocker_count": 0,
  "severity_counts": {"critical": 0, "major": 0, "minor": 1},
  "overall_score": 7.8,
  "art_direction_alignment": {
    "overall": 8,
    "lost_intent": []
  },
  "slides": [
    {
      "slide": 1,
      "visual_structure": "editorial",
      "reference_ids": ["cover-editorial-contrast"],
      "selected_candidate_id": "B",
      "scores": {
        "hierarchy": 8,
        "focal_point": 8,
        "composition": 7,
        "visual_interest": 8,
        "whitespace": 8
      },
      "art_direction_alignment": 8,
      "reference_intent_preserved": true,
      "ai_template_feel": "none",
      "issues": [
        {"code": "cover-caption-tight", "severity": "minor", "message": "封面副标题与页脚间距略紧"}
      ]
    }
  ],
  "deck": {
    "issues": []
  },
  "overall_summary": "<整体判断：这套版面可交付还是仍需返工，及理由>",
  "deck_rhythm": {"macro": "<全 deck 节奏判断>", "micro": "<页间衔接判断>"}
}
```

`reference_ids` 和 `selected_candidate_id` 只记录设计 provenance，不要求像素级复制。`reference_intent_preserved` 判断的是 focal ownership、silhouette/read path 和 positive design rationale 是否仍被保留。

## Score rubric

所有分数 1–10：

- `hierarchy`：标题、结论、证据主次是否一眼可辨；
- `focal_point`：是否存在唯一且明确的第一视线落点；
- `composition`：比例、对齐、留白和阅读路径是否自然；
- `visual_interest`：是否存在真实信息设计/视觉张力，而不是把内容装进默认框；
- `whitespace`：留白是否服务层级，而不是拥挤或“空但没设计”；
- `art_direction_alignment`：页面/整套是否真正执行确认后的 type scale、image treatment、chart/component language、motif 和 background rhythm。

High-score 默认每项不低于 6、整套平均不低于 7。Batch 4.4 起，`hierarchy` / `focal_point`
低于阈值属于 Major（页面结构性损坏，需要 repair）；`composition` / `visual_interest` /
`whitespace` 低于阈值与平均分不达标属于 **advisory**——照实写进报告、由管线计数，但不机械
阻塞交付。若 `art_direction_alignment < 6`，即使页面本身不难看，也要检查是否 style seed/art
direction 在生产时被丢失。

## visual_structure vocabulary

优先使用稳定名称：`cover`、`statement`、`typography`、`split`、`editorial`、`image-led`、`chart`、`diagram`、`flow`、`timeline`、`comparison`、`matrix`、`table`、`dashboard`、`quote`、`reference`、`equal-cards`、`card-grid`、`three-column`、`numbered-list`、`plain-list`、`other`。

`equal-cards / card-grid / three-column / numbered-list / plain-list` 是高复用风险结构。
连续两页同类、任意结构连续三页，在 `rigorous` 属 Major；在 `fast`/`standard` 留作改进建议。

## AI-template feel

- `none`：内容驱动，主次明确，有真实视觉决策；
- `minor`：局部仍有常见 card/icon 套路，但不主导页面；
- `major`：页面主要依赖等宽卡片、2×2、三等分、无意义 icon 或模板化组件填充。High-score 必须 repair。

## v0.8 必查：从 visual generation 到 final render 是否发生退化

逐页除常规问题外，至少判断：

- **Art Direction**：type scale、dominance、crop language、chart grammar、component language 是否真的出现，还是生产时又退回默认 PptxGenJS/安全 helper；
- **Reference intent**：reference 的 `why_it_works` 是否仍成立；例如本应“大数字先读、图表作证”，最终是否变成图表和四个框同权；
- **Candidate preservation**：high-leverage 页最终 silhouette/focal ownership 是否仍接近 selected candidate；如果改了，是否因为真实内容/asset 需要而合理；
- **Asset realization**：Art Direction 计划的 hero/evidence/chart/diagram 是否真正实现，还是缺素材后全部退化成 text+shape；
- **Typography**：标题/正文层级是否明显；typography 页是否真有 dominant thesis，而不是编号列表；
- **Image crop**：是不是一个决定性 crop，还是图片被缩成右侧小矩形；
- **Chart**：takeaway 是否先于图表被读到，是否仍是默认 chart chrome；
- **Cover/closing**：是否有可记忆的 visual thesis 和视觉呼应。
- **Palette consistency**：cover/section/closing 是否真的用了该风格的 `dark_palette`，还是生产时另挑了一套深色；把深浅两页并排放，强调色与中性色是否仍属同一色系。

如果 high-leverage 页 `reference_intent_preserved=false` 或 asset plan 明显未实现，默认至少 Minor；若因此页面落入 card-grid/weak hierarchy/无 focal point，则 Major。

## 冻结数值 × chart grammar：谁让路（v0.14.1）

三条规则在页面上会互相顶：actual-content 门要求每个 planned number 有**可见文本载体**
（chart 数据标签不算文本 run）；你自己按 chart grammar 会要求柱子可直读；而反冗余判定又会
把"同一数值出现两次"记成缺陷。不写清优先级，builder 就只能在夹缝里来回改——2026-09-17 live
第 5→7 轮就是这样震荡的（删直标 →"最高两根柱无法直读"→ 加回直标 →"18.4 被陈述三次"），
最后一轮还把一直通过的 `actual_content` 门弄坏了。

仲裁规则：

1. **冻结数值的文本载体不是冗余。** planned number（见 `page_brief.py` 输出的
   `numbers`，与 actual-content 门同源）在页面上必须且只须由一个文本载体陈述。这个载体
   不得被记为 `triple-encoding` / `left-rail-duplicates` / `dual-value-per-bar` 之类的重复缺陷。
2. **同一数值已有文本载体时，图表的直标可省略，且不得因缺直标判 Major。** 可读性由文本载体
   满足；"最高两根柱无法直接读取"只有在页面上**任何地方**都读不到该数值时才成立。
3. **真正的重复缺陷有三种**，必须点名是哪一种：
   - 同一数值被两个**文本**载体陈述（居中大数字 + 柱上数值标签 + 要点句同值）；
   - 一根柱旁并排两个数值，柱高对应哪个无法判定；
   - 左栏把右栏柱图的数值逐条抄一遍，不提供新信息。
4. 判定前先读 `page_brief.py` 输出的该页 `numbers`：它们是冻结要求，属于豁免面。写 issue 时
   要说明"这个数值的文本载体是冻结要求的"，否则 repair 会去删掉门要求的东西。
5. 缺图导致的"asset plan 未实现"（hero/evidence visual 从未落地）按 asset 层判，但请把
   `art-direction` 的 `asset_plan` 与页面对照后再下结论：计划里声明的图，页面上没有就是
   Major，不要用"文字已足够"替它开脱。

## Deck-level rhythm

整套至少判断：

- 强页/弱页、密页/疏页、image/chart/diagram/type 页是否有节奏；
- background rhythm 是否按 Art Direction 有能量变化，而不是整套一个白底；
- 中段是否连续卡片/列表；
- focal point 是否随 narrative action 变化；
- motif 是否有持续性但不过度重复；
- visual asset mix 是否足以让 8–10 页看起来像“一套设计”，而不是“八张排版正确的文档截图”。

## Repair classification

遇到 Major/Critical 先判断修复层级，不要所有问题都只改 x/y：

```yaml
slide: 6
problem: "最终页虽然无重叠，但 selected candidate 的递进路径退化成四个等宽模块"
repair_level: "composition"   # art-direction | reference | composition | asset | implementation
repair:
  - "保留四层缓解逻辑，重新采用 central-spine / asymmetric-decision reference"
  - "只把 RAG 设为主节点，其余三层降权"
  - "删除等宽卡片背景，用连接关系和字号层级承担结构"
```

- `art-direction`：整套视觉概念/类型/asset mix 本身太弱；
- `reference`：当前 positive prior 选错；
- `composition`：candidate/read path/focal ownership 失效；
- `asset`：缺图、图裁切、图表/diagram 选择错误；
- `implementation`：spacing、wrap、overlap、contrast 等执行问题。

修复后必须 rebuild → package/readback → render → 重写 visual-review.json。旧 visual report 的 PPTX hash 不能复用。
