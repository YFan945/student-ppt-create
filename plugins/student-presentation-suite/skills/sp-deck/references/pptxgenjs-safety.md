# pptxgenjs Generation Rules

本文件只维护生成 deck.js 时的 PptxGenJS gotchas。页面视觉、共享版式和 QA 分别以
`visual-style-menu.md`、`layout-library.json` 和 `pptx-qa.md` 为准。创建/重建默认加载
`pptx-helpers.js` 执行安全检查；layout、visual、shape、SVG 和 composer 库均为可选建议或
fallback，不是逐页模板。逐页渲染检查是 complete 交付
的必要证据。wrapper 只在生成后做 `normalize-generated`（修复类），不做静态门禁。

## 布局与坐标

1. 添加 slide 前先设 `pres.layout`。默认画布 `LAYOUT_16x9` = 10" × 5.625"；
   坐标超出边缘不会被裁剪，只是画不上。需要更宽画布用 `LAYOUT_WIDE`（13.3" × 7.5"）。
2. 坐标必须落在画布内；建议最小边距 0.5"，内容块间距 0.3-0.5" 并保持一致。

## 颜色与透明度

3. 颜色用 6 位 hex，**不带 `#`，不带 8 位 alpha**（`#FF0000` 和 `"00000020"` 都损坏
   文件）。透明度：fill/image 用 `transparency: 0-100`，shadow 用 `opacity: 0.0-1.0`，
   二者不通用。
4. 渐变填充不支持——需要渐变时用渐变图片当背景。

## 对象与阴影

5. pptxgenjs 会**原地修改 option 对象**（首次使用时把值转成 EMU）。绝不跨多个
   `add*` 调用共享同一个 `shadow`/options 对象——每次新建。
6. shadow `offset` 必须 ≥ 0，负数会损坏文件；向上阴影用 `angle: 270` + 正 offset。
7. `letterSpacing` 被静默忽略，真选项是 `charSpacing`。
8. `rectRadius` 只对 `ROUNDED_RECTANGLE` 生效，`RECTANGLE` 上无效。

## 文本与列表

9. 列表：每一项设 `bullet: true`，禁止在文本里写字面量 `•`（会渲染成双子弹）。数组项
   除最后一项外设 `breakLine: true`。段间距用 `paraSpaceAfter`。行距必须用**磅值**
   `lineSpacing: fontSize * 1.18`（与 helper / registry / 实际渲染一致）。禁止
   `lineSpacingMultiple`（它乘的是字体自然行高 ≈1.2× 字号，不是字号本身）；禁止把
   `lineSpacing` 写成 `1.18` 这种倍数——pptxgenjs 会当成 1.18 磅，文字不可见。
10. 文本框有内建内边距——文字要与形状/线条/图标对齐到同一 x 时设 `margin: 0`。
11. 字号下限由共享 design tokens 决定；不得为了适配而在脚本中静默突破。

## 实例与输出

12. 每个输出文件创建一个新的 `new pptxgen()` 实例，绝不复用。
13. `slide.addNotes("...")` 写入演讲者备注（纯文本，每页一次）；绝不放文本框里。

## 图表

14. PowerPoint 原生能画的都用 `addChart()`，保持可编辑；组合图传数组
    `[{type, data, options}]`。
15. 默认 chart 是裸的：必须设 `showTitle` + `title`、`showValue: true` +
    `dataLabelPosition`、`chartColors`（从调色板取），并静默 frame
    （`catAxisLabelColor`/`valAxisLabelColor`、`valGridLine: { color, size }`、
    `catGridLine: { style: "none" }`、单系列 `showLegend: false`）。
16. stacked bar/column 的 `dataLabelPosition` 只能是 `ctr`/`inEnd`/`inBase`；
    `outEnd` 会损坏文件。
17. 组合图用 secondary 轴时必须同时声明 `valAxes` 和 `catAxes` 各两条，否则 PowerPoint
    丢弃该图表。normalize 会移除未声明的 `c:axId`（pptxgenjs 对普通单系列 chart 也会写一个
    多余轴引用，属常规修复）；若模型本意是双轴组合图，`run_with_pptxgenjs.js` 会在生成期
    **报告警提示**（不阻断），须在 generator 里显式声明双轴。库不暴露的原生功能（趋势线、
    误差线）自己算系列或后处理 OOXML，不回落成渲染图片。
18. `writeFile()` 后必须跑 `python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" validate
    <pptx> --output <package-report.json> --json`；报告里命名的 chart/slide 缺陷要修在
    generator 里重建，不是手改打包后的 XML。

## 包结构

19. **永不重排 `<p:presentation>` 的 children 顺序**。pptxgenjs 把
    `<p:notesMasterIdLst>` 写在 `<p:sldIdLst>` 之后、两个 master 指向同一个 theme，
    PowerPoint 读这个顺序没问题；挪动该元素 deck 就打不开了。schema 校验会用临时副本
    重排，盘上文件保持官方顺序。

## 图片与图标

20. 图片走 `addImage({ data: "image/png;base64," + buf.toString("base64") })`——
    前缀必须带。图标默认用内置库 `pptx-icons.js`
    （`I.addIconFromLibrary(slide, name, box, tokens, role)` / `I.iconSVG(name, color)`，
    约 30 个常用矢量图标，`addImage` base64 嵌入、随 token 着色）；自绘
    `addText`/`addShape` 或手写内联 SVG 为后备；不引入外部图标库。库中无合适图标且自绘
    难以保持一致时，按项目临时安装并注明在生产 brief 中。

## 字体安全表（QA 可信）

写进 pptx 的字体由用户机器的 PowerPoint 渲染，QA 用 LibreOffice 会替换字体、宽度可能
不同。为让 QA 的 text-fit 检查可信：

- **安全字体**（QA 宽度一致 + 随 Office 分发）：Arial、Calibri、Cambria、Times New
  Roman、Courier New、Bookman Old Style、Century Schoolbook。正文和任何需要对齐的文本
  用这些。
- **有性格的标题**：安全衬线（Cambria/Bookman Old Style/Century Schoolbook）+ 安全
  无衬线正文（Calibri/Arial），零 QA 风险。
- **QA 不可靠字体**（替换后宽度不同，overflow 检查可能错）：Georgia、Trebuchet MS、
  Impact、Arial Black、Garamond、Consolas、Palatino Linotype、Calibri Light。用户点名
  才用，容器留 ~10% slack，不信任 QA 的 text-fit。
- **绝不默认 Aptos**：Office 2023+ 默认字体在此无 metric 兼容替换、老 Office 又缺失，
  两端都不可靠。

## Runtime helper 使用守则

- 默认用 `H.safeArea`/`H.gridLayout`/`H.color`/
  `H.addBackground` 和 `V.renderVisual` 降低手算坐标与组件契约错误。
- `H.assertTextFits` 只 `console.warn` 不阻断生成；溢出靠 QA 逐页视觉检查兜底。
- 页面默认可自定义构图；可先用 `L.suggestLayouts` 获取候选。只有 `layout_lock: true`、模板
  复现或确定性 fallback 才直接 `L.resolveLayout`。所有页面仍须满足本文件 gotchas、容量和视觉 QA。
