# Main-session production

主会话直接读取素材、编写页面、查看当前预览并修复。Python 负责执行工具，不派发模型或评判审美。

## Commands

完成 intake 后，工作目录为项目 `outputs/.pptx-work/<work-id>`：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan --work-dir <wd> --slide-spec <spec> --repair-limit 3
# 主会话实现 pages/pNN-*.js（编辑模式改 ooxml/）。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" run --work-dir <wd>
# 主会话查看返回的预览、实际文本和讲稿；有问题直接改，再 run。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" complete --work-dir <wd>
```

`plan` 自动验证 Spec 并生成源码；`--art-direction` 可选，仅用于已有设计配置。研究任务可提供 `--research-pack`，工具批量编译证据。无需先调用多个验证或状态推进命令。

`run` 执行构建、字体处理、事实精确项、包与作者几何报告检查和全页渲染，返回 `technical_checks`、`geometry`、`review_required` 及当前页面路径。`ok` 只表示列出的技术检查通过，不代表审美、核心语义或逐页看图已经验收。几何 warning 和字体替换供作者对照完整渲染判断；合理的装饰覆盖不按数量阻断。默认首次生成加 3 轮修复；任务明确更低预算时用该预算。当前文件与预览绑定一致时可复用渲染。

`complete` 绑定当前产物并生成已确认的辅助文件。主会话在调用前完成看图和核心语义自检；工具不假装替作者做独立视觉评审。`status` 可以读取历史 manifest，旧管线任务须保留原件后以新 work-id 继续。

交付前必须渲染所有最终页面，总览看节奏，再逐页完整查看断行、裁切、意外重叠、连接线、标签归属、页码、信息密度、颜色层级和图文关系。有参考文件时对照真实页面，而不是只对照默认设计 token。修复后再次 `run`，查看变化页并扫描全套；最后确认内容、素材来源和用户要求。自动报告不证明美观、事实语义正确或已在 PowerPoint 中实测。

## Authoring

学生内容页优先实现充分的证据、丰富的视觉表达与有层次的颜色；按需使用 [可运行视觉示例](main-session-visual-examples.md)。下面的短代码只说明接口，不能作为整套学生 PPT 的视觉质量范本。

`deck.js` 负责装配、登记、背景与讲稿。`auto` 页面导出函数，可直接使用 pptxgenjs 和共享工具；不必先选择 move 或固定模板。标题、文字和视觉元素均可编辑。函数的 `presentation_copy` 写实际标题与标签，`notes` 写真实讲稿。

```javascript
'use strict';
module.exports = function (ctx) {
  const { H, slide, tokens } = ctx;
  H.addFittedText(slide, '从查询到回答', { x: 0.6, y: 0.5, w: 8.8, h: 0.8 },
    tokens, 'chinese', 'title', { fontSize: 32, margin: 0 });
  const labels = ['查询', '检索证据', '生成回答'];
  labels.forEach((label, index) => {
    const x = 0.6 + index * 3.1;
    // 节点承载步骤，连接线承载先后关系；没有装饰面板。
    H.addFittedText(slide, label, { x, y: 2.1, w: 2.4, h: 0.8 },
      tokens, 'chinese', 'body', { fontSize: 26, margin: 0 });
    if (index < labels.length - 1) slide.addShape('line', {
      x: x + 2.5, y: 2.5, w: 0.45, h: 0,
      line: { color: H.color(tokens, 'accent'), width: 2, endArrowType: 'triangle' },
    });
  });
};
module.exports.presentation_copy = { headline: '从查询到回答', visual_labels: ['查询', '检索证据', '生成回答'] };
module.exports.notes = '先输入查询，再检索证据，最后基于证据生成回答。';
```

图片按真实长宽比与关键保留区域构图：

`addPlannedImage` 默认等比例显示完整图片。仅明确 `crop_suggestion: 'cover'` 或合法 `crop` 区域时裁切；`preserve_region` 保留证据区域。原生 sizing 的可见范围会与几何登记保持一致。

```javascript
H.addPlannedImage(slide, {
  path: '/absolute/path/paper-figure.png', width: 1200, height: 800,
  preserve_region: { x: 0, y: 0, w: 1, h: 1 },
}, { x: 0.5, y: 1.5, w: 6.2, h: 3.6 }, ctx.pptx);
H.addFittedText(slide, '图中重点的解释', { x: 7, y: 1.6, w: 2.5, h: 2 },
  tokens, 'chinese', 'body', { fontSize: 23 });
```

真实比较数据使用原生图表，系列值从用户材料或证据文件读取，不编造基线：

```javascript
slide.addChart(ctx.pptx.ChartType.bar, [{ name: '实测结果', labels: data.labels, values: data.values }], {
  x: 0.8, y: 1.6, w: 8.4, h: 3.1,
  catAxisLabelFontFace: 'Microsoft YaHei', catAxisLabelFontSize: 16,
  valAxisLabelFontSize: 16, chartColors: [H.color(tokens, 'accent')],
  showLegend: false, showValue: true,
});
```

布局工具参考 `pptxgenjs-helper-api.md`，图表结构参考 `pptxgenjs-safety.md`。`guided` 的完整句子使用 `statement_pt` 或 `key_statement_pt`，`stat_pt` 用于数值。`cover_title_pt`、`slide_title_pt` 映射到对应页面的标题角色。未知字号键会给出具体错误，不会悄悄忽略。

信息不足时保留事实边界；图片缺失时改变表达，不画空框或添加无意义图标。中文普通文本与 rich-text 共用实测断行；最终以渲染结果为准，不制定统一字号地板。
