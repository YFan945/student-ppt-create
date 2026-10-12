# PPTX Production

创建与编辑都由主会话执行。先确认 Production Summary，整理 Slide Spec 和真实素材，再直接实现页面、构建渲染、看图修复和导出。

完整命令与源码写法见 [main-session-production.md](main-session-production.md)。

工具内部通过 `scripts/run_with_pptxgenjs.js` 构建并处理字体，通过
`scripts/pptx_tool.py` 的自有运行时完成包操作及渲染；不由模型逐步编排。

`auto` 默认自由坐标；布局和 move 可选。直接复用 suite-owned 图片、图表、文本度量及 OOXML 工具，不引入外部运行时，不创建页面或评审子代理。优先表达信息关系，保留事实、来源和用户指定的品牌。
