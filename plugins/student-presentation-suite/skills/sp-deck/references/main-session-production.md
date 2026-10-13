# Main-session production

主会话直接读取素材、编写页面、查看当前预览并修复。Python 负责执行工具，不派发模型或评判审美。

## Commands

完成 intake 后，工作目录为项目 `outputs/.pptx-work/<work-id>`：

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan --work-dir <wd> --slide-spec <spec>
# 主会话实现 pages/pNN-*.js（编辑模式改 ooxml/）。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" run --work-dir <wd>
# 主会话查看返回的预览、实际文本和讲稿；有问题直接改，再 run。
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" complete --work-dir <wd>
```

`plan` 自动验证 Spec 并生成源码；`--art-direction` 可选，仅用于已有设计配置。研究任务可提供 `--research-pack`，工具批量编译证据。无需先调用多个验证或状态推进命令。

`run` 执行构建、字体处理、事实精确项、包与作者几何报告检查和全页渲染，返回 `technical_checks`、`geometry`、`review_required` 及当前页面路径。`ok` 只表示列出的技术检查通过，不代表审美、核心语义或逐页看图已经验收。几何 warning 和字体替换供作者对照完整渲染判断；合理的装饰覆盖不按数量阻断。不以金额、token 或修复次数阻断当前工作。当前文件与预览绑定一致时可复用渲染。

`complete` 绑定当前产物并生成已确认的辅助文件。主会话在调用前完成看图和核心语义自检；工具不假装替作者做独立视觉评审。`status` 可以读取历史 manifest，旧管线任务须保留原件后以新 work-id 继续。

交付前必须渲染所有最终页面，总览看节奏，再逐页完整查看断行、裁切、意外重叠、连接线、标签归属、页码、信息密度、颜色层级和图文关系。有参考文件时对照真实页面，而不是只对照默认设计 token。修复后再次 `run`，查看变化页并扫描全套；最后确认内容、素材来源和用户要求。自动报告不证明美观、事实语义正确或已在 PowerPoint 中实测。

## Authoring

新任务 pages/ 导出页面函数：直接使用 ctx.slide（pptxgenjs）、ctx.pptx 和按需选用的 ctx.H。完整画布可用，背景和版式由页面源码绘制；脚手架不放置任何视觉元素，不按 design_freedom 限制函数或自动选择布局。presentation_copy 记录实际标题/标签；notes 写讲稿。

从事实材料和参考页面设计构图，保留必要的解释、证据与细节。使用组件时由作者选定输入与区域，不把其内部示例坐标复制成整套页面格式。接口查阅 pptxgenjs-helper-api.md、pptxgenjs-safety.md；图文实现可参阅 main-session-visual-examples.md。

图片按真实比例与证据保留区域布局；addPlannedImage 默认完整显示，明确裁切才使用 cover/crop。图表使用有来源的数据。调用原生或共享文本工具时可直接指定字号、字体、对齐、边距和坐标；最终检查实际渲染。
