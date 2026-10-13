# pptxgenjs Generation Rules

本文件只维护生成 deck.js 时的 PptxGenJS gotchas。页面视觉、共享版式和 QA 分别以
`../../../references/model-led-design.md` 与当前生产流程为准。创建/重建默认加载
`pptx-helpers.js` 执行安全检查；layout、visual、shape、SVG 和 composer 库均为可选建议或
fallback，不是逐页模板。逐页渲染检查是 complete 交付
的必要证据。wrapper 只在生成后做 `normalize-generated`（修复类），不做静态门禁。

## 布局与坐标

1. 添加 slide 前先设 `pres.layout`。默认画布 `LAYOUT_16x9` = 10" × 5.625"；
   坐标超出边缘不会被裁剪，只是画不上。需要更宽画布用 `LAYOUT_WIDE`（13.3" × 7.5"）。
2. 以实际画布检查真实裁切与溢出；边距和内容间距由构图决定。

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

9. 使用 `bullet: true` 时不要再添加字面量 `•`。需要换行的 rich-text run 设置 `breakLine: true`。`paraSpaceAfter` 和 `lineSpacing` 的单位是磅；选择适合字号的实际行距，不能将倍数当磅值写入。
10. 文本框有内建内边距——文字要与形状/线条/图标对齐到同一 x 时设 `margin: 0`。
11. 新任务由作者选择有效字号，按实际渲染检查可读性；旧任务保持已确认的控制。

## 实例与输出

12. 每个输出文件创建一个新的 `new pptxgen()` 实例，绝不复用。
13. `slide.addNotes("...")` 写入演讲者备注（纯文本，每页一次）；绝不放文本框里。

## 图表

14. PowerPoint 原生能画的都用 `addChart()`，保持可编辑；组合图传数组
    `[{type, data, options}]`。
15. 图表标题、数据标签、图例、颜色及网格线按表达需要设置，保留必要单位与来源。
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

20. base64 图片的 data 前缀需带 MIME，例如 `image/png;base64,`。图标可使用内置库、原生形状、SVG 或可获得的素材；选择能正确渲染且适合页面的实现。

## 字体与渲染

使用可获得的字体并进行实测。LibreOffice 与目标 PowerPoint 的字体替换可能造成宽度差异；查看字体替换报告与最终渲染，必要时改字体或调整文本区域。

## Runtime helpers

按需使用 [helper API](pptxgenjs-helper-api.md) 和组件库。主会话自由编写页面；生成、几何检查与渲染按 [main-session-production.md](main-session-production.md) 执行。
