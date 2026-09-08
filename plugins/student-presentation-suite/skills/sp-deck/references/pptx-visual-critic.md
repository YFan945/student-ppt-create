# Structured Render Visual Critic

v0.7.1 把视觉复核从“有没有溢出/重叠”升级为**真实页面的设计审查**。本文件定义模型逐页查看 render 后必须写出的最小 `visual-review.json`。它不是静态分析的替代品，而是把主观设计判断变成可追踪、可返工、可被 delivery gate 校验的结构化证据。

## 核心原则

1. 先看真实 render，再写报告；不得根据 Slide Spec、deck.js 或自我想象代替看图。
2. `没有 overflow/overlap` 只代表工程可用，不代表设计优秀。
3. High-score deck 的 Major/Critical 视觉问题必须进入 repair，不能只记录后继续 complete。
4. 视觉问题优先修 actual artifact。不要为了让 readback 或视觉报告通过而反向修改已冻结 Slide Spec；只有计划本身确实错误时才走显式 spec revision。
5. 逐页之外必须检查整套节奏。连续两页等宽卡片、普通列表、三等分栏属于明显的 AI-template repetition 风险。

## visual-review.json

```json
{
  "pptx_sha256": "<current pptx sha256>",
  "slides": [
    {
      "slide": 1,
      "visual_structure": "statement",
      "scores": {
        "hierarchy": 8,
        "focal_point": 8,
        "composition": 7,
        "visual_interest": 7,
        "whitespace": 8
      },
      "ai_template_feel": "none",
      "issues": [
        {
          "severity": "Minor",
          "code": "cover_motif_weak",
          "message": "封面干净，但核心视觉命题仍偏弱。",
          "resolved": true
        }
      ]
    }
  ],
  "deck": {
    "issues": [
      {
        "severity": "Major",
        "code": "repetitive_middle_section",
        "message": "第 5、6 页连续使用等权卡片，页面节奏单调。",
        "resolved": true
      }
    ]
  }
}
```

## Score rubric

所有分数均为 1–10：

- `hierarchy`：标题、结论、证据的视觉主次是否一眼可辨。
- `focal_point`：是否存在唯一且明确的第一视线落点。
- `composition`：比例、对齐、留白和阅读路径是否自然。
- `visual_interest`：页面是否有真实的信息设计，而不是把内容装进默认卡片。
- `whitespace`：留白是否服务层级；既不过挤，也不是空得没有视觉张力。

High-score 默认要求：每项不低于 6，整套平均不低于 7。低于阈值属于 Major，需要 repair。

## visual_structure vocabulary

优先使用下列稳定名称，以便做 deck-level rhythm 检查：

- `cover`
- `statement`
- `typography`
- `split`
- `editorial`
- `image-led`
- `chart`
- `diagram`
- `flow`
- `timeline`
- `comparison`
- `matrix`
- `table`
- `dashboard`
- `quote`
- `reference`
- `equal-cards`
- `card-grid`
- `three-column`
- `numbered-list`
- `plain-list`
- `other`

`equal-cards / card-grid / three-column / numbered-list / plain-list` 是高复用风险结构。连续两页使用同一个此类结构即视为 Major。任意结构连续三页也视为 Major。

## AI-template feel

- `none`：页面构图由内容驱动，主次明确。
- `minor`：局部仍有常见卡片/图标套路，但没有主导页面。
- `major`：页面主要依赖等宽卡片、三等分、2×2 卡片、无意义 icon 或模板化组件填充。High-score 下必须 repair。

## 必查问题

逐页至少判断：

- 是否只是“内容正确地装进框里”，却没有视觉焦点；
- 是否所有元素权重相同；
- typography 页是否只是编号列表换皮；
- 图表/结构图是否真正比文字更适合表达该关系；
- 封面是否有可记忆的视觉命题，而不是标题 + 副标题 + 大片空白；
- 是否为了“丰富”加入 filler icon/card/photo；
- 是否存在明显的 AI 卡片味。

整套至少判断：

- 连续页面是否重复同一种结构；
- 是否有强页/弱页、密页/疏页、图页/文字页之间的节奏；
- 开场与收尾是否形成视觉呼应；
- 中段是否陷入连续卡片或连续列表；
- 每页的 focal point 是否随叙事动作变化，而不是永远居中标题 + 四块内容。

## Repair output

遇到 Major/Critical 时，先写具体 repair instruction，再修改 generator。例如：

```yaml
slide: 6
problem: "与第 5 页连续使用四个等权模块，视觉节奏重复"
repair:
  - "保留四层缓解逻辑，但改为从左下到右上的递进路径"
  - "只把 RAG 作为主视觉节点，其余三层降低权重"
  - "删除等宽卡片背景，使用直角连接线与层级字号"
```

修复后必须重新 build → package/readback → render → 重写 visual-review.json。旧 visual report 的 PPTX hash 不能复用。
