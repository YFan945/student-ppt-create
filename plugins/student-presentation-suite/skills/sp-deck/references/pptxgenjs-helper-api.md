# PptxGenJS Helper API（`scripts/pptx-helpers.js`）

## 为什么有这份文档

一次 13 页 deck 的生成中，为了摸清 helper 有哪些可用函数，执行了 **25 条** `python -c` /
`node -e` 内联探针——其中"提取 helper 库的可用 API"一次就跑了 8 条命令。按本项目实测
成本模型（每次工具调用 ≈ 2 个请求 × 23 万 token），这 25 次探针约合 1200 万 token。

这份摘要 + `--describe` 把这件事压成一次读取或一条命令。

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
  `secondary_text` / `primary_accent` / `secondary_accent`），**不要硬编码 hex**
- `fontFamily(tokens)`、`fontSizeScale(tokens, lang)` — 字号与字体族同样来自 tokens
- `paletteMode(tokens, mode)`、`softShadow(tokens, overrides)`

**几何**

- `safeArea(slideW, slideH, tokens, opts)` — 页面安全区，是所有构图的起点
- `footerArea(slideW, slideH, tokens)` — 来源行区域；正文内容不得侵入
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

## 三条反复踩到的坑

1. **不要自己拼 hex。** 一律 `color(tokens, role)`，否则暗版页（封面 / 章节 / 结尾）
   会直接不可读，且通不过 `pptx_rendered_check.py` 的字号与对比度量测。
2. **先 `safeArea()` 再放元素。** 直接按画布边缘排会撞上安全边距，`registry` 会判
   `out_of_canvas`。
3. **长文本交给 `addFittedText`，不要手算行数。** 手写 `estLines` 容易漏算全角标点与
   项目符号缩进——第二轮就因为估算偏乐观，P9 重排了两次。
4. **小字必须走 `role`。** `addTextBox` 无 `role` 时字号下限是正文（CJK 22pt）：请求
   更小的值会被抬高并**打印警告**，不会静默生效。数据标签、注解、来源一律走
   `addTextBox(..., { role: 'caption' | 'source' | 'label' })`（角色字号表 11/12/16pt），
   或直接用 `addFittedText` + `role`。看到"请求字号 Xpt 低于正文下限"就是走错了通道。
5. **`color` 只接受 hex。** 传调色板角色名（`primary_text` 之类）会直接抛
   `RangeError`；正确写法是 `color(tokens, 'primary_text')`。旧行为是静默接受并渲染成
   不可读的文字，深色页要到独立评审才暴露。

## 什么时候才需要读源码

`--describe` 给签名，本文给用法。只有在需要确认**具体实现行为**（某个函数的降级
策略、取整方式）时才去读 `scripts/pptx-helpers.js`，并且只读那一个函数，不要整文件
读回上下文（CD-3）。
