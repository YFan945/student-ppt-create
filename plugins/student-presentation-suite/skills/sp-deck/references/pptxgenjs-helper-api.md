# PptxGenJS Helper API（`scripts/pptx-helpers.js`）

For new tasks follow [model-led design](../../../references/model-led-design.md).
New `fitText` uses
fontkit through the measured role policy. `addPositionedText` controls mixed
language spacing, and `addPlannedImage` protects image regions. Gallery, motif
and cover band use is optional.

For model-led pages, `module.typography` and `module.visual_language` record
page-specific choices. The harness captures direct drawing calls. Direct
`addTable` requires explicit cell dimensions (`colW`/`rowH` or `w`/`h`) and is
drawn as editable, measured cells; express merged cells with explicit shapes
and text. Free-page notes go in `module.notes` so the harness writes them once.

## 权威来源

```bash
node "${CLAUDE_PLUGIN_ROOT}/scripts/pptx-helpers.js --describe"
```

输出 JSON：画布尺寸、安全字体表、全部导出的名称 / 签名 / 元数。**它从 live exports
生成，不可能与代码漂移。** 下面这张表只负责说明"什么时候用哪个"，签名一律以
`--describe` 的输出为准——不要凭记忆写参数顺序。

## 画布

| 常量 | 值 |
| --- | --- |
| `SLIDE_W_IN` | 10 |
| `SLIDE_H_IN` | 5.625 |

与 `shared/pptx_runtime` 的 Python 侧常量一致，`tests/test_stack_contract.py` 锁定两侧
不得偏航。构图坐标一律以英寸为单位，不要用像素或 EMU。

## 按用途分组

**主题与 Token**

- `applyTokens(pptx, tokens, lang, opts)` — 建 deck 后第一件事，把 design tokens 装进去
- `color(tokens, role)` — 按角色取色（`canvas` / `surface` / `primary_text` /
  `secondary_text` / `primary_accent` / `secondary_accent`）；页面也可使用有效的自定义 hex 配色
- `fontFamily(tokens)`、`fontSizeScale(tokens, lang)` — 字号与字体族同样来自 tokens
- `paletteMode(tokens, mode)`、`softShadow(tokens, overrides)`

**几何**

- `safeArea(slideW, slideH, tokens, opts)` — 可选页面安全区建议
- `footerArea(slideW, slideH, tokens)` — 可选来源行区域
- `gridLayout(area, columns, rows, opts)`、`weightedColumns(area, count, weights, gap)`
- `spacing(tokens, step)`、`cornerRadius(tokens)`

**文字适配**（这一组最容易用错）

- `addFittedText(slide, text, box, tokens, lang, role, options)` — **首选入口**，会按
  role 自动降字号并登记几何
- `preflightText(text, box, tokens, lang, role, options)` — 只算不画
- `estimateTextFit(text, boxW, boxH, fontSize, isCJK)` — 返回
  `{ lines, fillRatio, overflow }`
- `assertTextFits(...)` — 超限仅警告并返回 fit（辅助区域如页脚使用）
- `requireTextFits(...)` — 超限直接抛错；`addTextBox` 的写入前置检查走它，
  溢出类缺陷在生成时消灭，不留给修复轮
- `plainText(text)` — 提取纯文本，回读比对时使用

**组件**

- `addTitle` / `addBody` / `addTextBox` / `addFooter` / `addAccentCard` / `addDivider`
- `addBackground(slide, tokens, dark)` / `addStyleMotif(slide, area, tokens, intensity)`

## 使用注意

- 自定义颜色使用有效 hex；`color(tokens, role)` 用于读取配色角色。
- 文字使用实测适配接口；`role` 用于语义和样式默认值，新任务可以直接指定有效字号。
- 构图以实际画布为边界；安全区和页脚区域按页面内容选用。

## 什么时候才需要读源码

`--describe` 给签名，本文给用法。只有在需要确认**具体实现行为**（某个函数的降级
策略、取整方式）时才去读 `scripts/pptx-helpers.js`，并且只读那一个函数，不要整文件
读回上下文（CD-3）。
