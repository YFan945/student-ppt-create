# Structured Render Visual Critic

v0.7.1 把视觉复核从“有没有溢出/重叠”升级为真实页面设计审查；v0.8 进一步要求 critic 判断**最终 render 是否兑现了 Art Direction、reference/candidate 的设计意图，以及生成阶段是否因为过度保守而丢掉视觉张力**。本文件定义查看真实 render 后必须写出的 `visual-review.json`。

## 核心原则

1. 先看真实 render，再写报告；不得根据 Slide Spec、deck.js、candidate JSON 或自我想象代替看图。
2. `没有 overflow/overlap` 只代表工程可用，不代表设计优秀。
3. High-score deck 的 Major/Critical 视觉问题必须 repair，不能只记录后 complete。
4. 视觉问题优先修 actual artifact；不要为了过检查反向修改 frozen Slide Spec。
5. 必须检查整套节奏：连续弱卡片/列表/三等分属于 AI-template repetition 风险。
6. **Author/critic separation**：如果当前执行环境能使用独立 review context、subagent 或重新开启一个不带 deck.js 细节的视觉审查上下文，优先这么做。无法分离时，也必须先隐藏/放下实现代码，只依据 full-resolution renders + Art Direction 目标复核，避免“因为自己刚写完所以自动觉得合理”。
7. v0.8 critic 不只是给分：如果最终页明显弱于选定 wireframe/reference 的视觉命题，应指出是哪一步退化（asset、hierarchy、crop、composition、type scale 或实现保守化）。
8. **配色一致性**：整套只能使用所选风格的两套 palette（light `palette` + 对应 `dark_palette`）。
   深色封面/章节/收尾页必须来自 `dark_palette`，不能是生成时临时挑的深色；发现任何 palette
   之外的强调色或底色、或直接写死的 hex，按 `art-direction` / `implementation` 返修。

## visual-review.json

```json
{
  "pptx_sha256": "<current pptx sha256>",
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
      "issues": []
    }
  ],
  "deck": {
    "issues": []
  }
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

High-score 默认每项不低于 6、整套平均不低于 7。低于阈值属于 Major，需要 repair。若 `art_direction_alignment < 6`，即使页面本身不难看，也要检查是否 style seed/art direction 在生产时被丢失。

## visual_structure vocabulary

优先使用稳定名称：`cover`、`statement`、`typography`、`split`、`editorial`、`image-led`、`chart`、`diagram`、`flow`、`timeline`、`comparison`、`matrix`、`table`、`dashboard`、`quote`、`reference`、`equal-cards`、`card-grid`、`three-column`、`numbered-list`、`plain-list`、`other`。

`equal-cards / card-grid / three-column / numbered-list / plain-list` 是高复用风险结构。连续两页同类即 Major；任意结构连续三页也 Major。

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
