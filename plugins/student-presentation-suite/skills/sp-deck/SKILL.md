---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.30.8
---

# Student Presentation PPT

主会话直接创作可编辑 PPTX，连续完成构图、实现、看图和修改。仅大纲走 `sp-outline`，只读诊断走 `sp-review`。不派发页面或视觉评审子代理。

展示正文与讲稿执行 `../../references/shared-standards.md` 的 Audience-facing Content 规范；正文直接呈现实质内容，制作与验证说明留在交付对话。

**常规创建的入口完整性**：authoring-quickstart.md 和 plan 返回的源码/输入已足够开始页面实现。第一次构建前不阅读 runtime、registry、文本测量器或事实验证器源码，也不重复导出整个 schema/API；直接使用受支持接口实现并 run。只有实际报错指向具体行为、快速说明与单函数帮助无法解释时才定点查看该函数。检查实现原理不是生产步骤，禁止用它替代创作。已有参考件则比较信息表达，不能以“自由设计”省略素材、模块支撑或层级。

路径以当前 skill Base directory 为准：根规范在 `../../references/`，工具在 `${CLAUDE_PLUGIN_ROOT}/scripts/`；已加载技能后不再查找缓存版本或遍历插件树。初始化/确认命令见快速说明。

按 references/main-session-production.md 的 Minimal reference path 加载当前任务所需规则，读过的不重读。规划归属在已有handoff-plan.md简表中记录；看图后的具体发现可通过complete的--review-note留在已有质量报告，不新增独立门禁。

## Workflow

1. 先区分当前要求与粘贴的历史过程记录，读材料并发现缺失/矛盾后，按 `../../references/presentation-intake.md` 集中完成必要澄清、Production Summary 与确认；仅用户尚未授权的事项需要询问。产物放在项目 `outputs/`，保留源 PPTX。
2. 汇总冻结事实、精确文字、数字、来源和用户品牌要求。先按 `../../references/content-workflow.md` 规划整套信息递进，选择拆解方法、组织充分正文和证据/解释组，检查跨页论点重复，不能只排标题和一句用途。新 Slide Spec 用 2.1，展示文案可重写或视觉化，保留必要解释与支撑；旧 1.0/2.0 保留文案匹配契约。外部事实检索按 `sp-research` 使用研究员，不把图片构图委派出去。
3. **先读素材再构图**：批量查看真实图片及其尺寸、焦点和保留区域。按 `../../references/model-led-design.md` 保持充实正文与选择性重点讲解，积极用工具获取/生成主题图片及制作可编辑表格、图表和结构图。先核对能力与已有授权；仅涉及图片获取/占位时读取 `../../references/image-sourcing.md`，原生无图任务不加载完整图片获取规则；缺素材时可用已确认允许的设计占位图，不编造数据。按需读 `references/main-session-visual-examples.md`；封面/模板任务读 `references/cover-and-template.md`。字数上限只记录明确要求。
4. 按 `../../references/content-to-visual.md` 在已有规划中明确各页主要图片/表格/统计图/具体图解及来源或生图/占位方案，对照整套主体布局变化与统一视觉语言；小图标仅辅助，不反复填充同一纸张/勾选符号。用户允许的图片占位可显示具体生成提示词。阅读 references/main-session-production.md，再调用 `ppt_pipeline.py plan` 创建薄装配文件和逐页源码。Art Direction 可选；不创建校准、Packet、分片或评分文件。
5. **主会话直接读写 pages/**。脚手架提供完整画布的页面函数及事实输入，不注入预设版式、背景、分区或字号表。直接使用 pptxgenjs 和按需选用的 helpers。素材和内容决定字号、布局和信息密度，讲稿不替代必要的上屏解释。先读 references/authoring-quickstart.md；其他接口规则只按当前操作查询，不提前研究字体/事实验证实现。参考件或丰富视觉任务按 ../../references/content-to-visual.md 检查主题对象、证据、关系和层级。
6. 调用一次 `ppt_pipeline.py run`，工具批量构建、处理中文字体、检查精确事实和包结构并渲染。它返回当前页面图、具体问题和待自检的核心信息，不派发代理。
7. **主会话查看所有当前渲染页并直接修复**。按 `references/main-session-production.md` 检查层级、重点、正文充实度、封面、模板及允许的占位图；总览看节奏，再完整看每页，并按目标观看条件检查缩放可读性。对照实际文本和简短讲稿核对核心信息及讲解路径。技术检查 `ok` 不代表视觉合格；自检不称为独立评审。修改后再次 `run`，按 changed_pages 检查全部受影响的最终完整页（共享文件影响所有引用页），查看最新总览；读取已有结果使用 status，不能为查看摘要再次构建。
8. 看图和内容自检完成后调用 `ppt_pipeline.py complete`，只导出已确认类型。它核验当前产物与检查/预览的绑定，生成的讲稿来自最终 PPTX 备注。导出路径由工具绑定，不在 complete 后手工搬文件；用 status 核验交付有效性。真实阻塞或未完成工作如实说明，保留当前产物继续修复。

## Commands

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan --work-dir <wd> --slide-spec <spec>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" measure --work-dir <wd>  # 可选：不构建，一次报出全部文本溢出
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" run --work-dir <wd>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" complete --work-dir <wd>
```

状态摘要、artifact bindings 和构建报告由工具写入，不让模型手工同步。低层图片、OOXML 编辑、原生图表与渲染工具继续使用 `scripts/pptx_tool.py` 及共享 helpers。

## Output contract

交付已确认的 PPTX、预览、PDF或辅助文件；不自动增加类型。工作目录为 `outputs/.pptx-work/<work-id>`，其中的报告属于工作记录。编辑须有 `change-summary.md` 并保持源文件。2.1 的 `presentation_copy` 记录实际标题与标签，冻结语义由主会话自检，精确项由 PPTX 回读检查。

旧 manifest 可用 `status` 读取，不自动迁移或继续执行已删除的子代理管线。需要继续旧成品时，以保留原件的新编辑任务开始。
