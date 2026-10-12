---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.30.0
---

# Student Presentation PPT

主会话直接创作可编辑 PPTX，连续完成构图、实现、看图和修改。仅大纲走 `sp-outline`，只读诊断走 `sp-review`。不派发页面或视觉评审子代理。

## Workflow

1. 按 `../../references/presentation-intake.md` 完成 Production Summary 与确认；仅用户尚未授权的事项需要询问。产物放在项目 `outputs/`，保留源 PPTX。
2. 汇总冻结事实、精确文字、数字、来源和用户品牌要求。新 Slide Spec 用 2.1，展示文案可压缩或视觉化；旧 1.0/2.0 保留文案匹配契约。外部事实检索按 `sp-research` 使用研究员，不把图片构图委派出去。
3. **先读素材再构图**：批量查看真实图片及其尺寸、焦点和保留区域。为每页决定需要解释的关系及其表达方式。图表、图片、结构图用于解释；封面或转场可简洁。不要靠装饰色条、重复卡片或孤立的大句子充数，不为作图编造数据。
4. 阅读 `references/main-session-production.md`，调用 `ppt_pipeline.py plan` 创建薄装配文件和逐页源码。Art Direction 可选；不创建校准、Packet、分片或评分文件。
5. **主会话直接读写 `pages/`**。新任务默认 `auto`：自由坐标调用共享绘图工具。`guided`/`deterministic` 是用户或作者选择的工具，不是每页必须经过的步骤。实际字号由作者决定，无统一下限和比例。按需读取 `references/pptxgenjs-helper-api.md` 和 `references/pptxgenjs-safety.md`。
6. 调用一次 `ppt_pipeline.py run`，工具批量构建、处理中文字体、检查精确事实和包结构并渲染。它返回当前页面图、具体问题和待自检的核心信息，不派发代理。
7. **主会话查看当前渲染页并直接修复**。总览看节奏，完整单页看断行、可读性、图文关系、裁切和证据。对照实际文本和讲稿核对核心信息；自检不称为独立评审。按原预算修改后再次 `run`，处理当前问题，不重复读取无变化的整套输入。
8. 看图和内容自检完成后调用 `ppt_pipeline.py complete`，只导出已确认类型。它核验当前产物与检查/预览的绑定，生成的讲稿来自最终 PPTX 备注。预算耗尽如实交付 `incomplete`。

## Commands

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" plan --work-dir <wd> --slide-spec <spec>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" run --work-dir <wd>
python "${CLAUDE_PLUGIN_ROOT}/skills/sp-deck/scripts/ppt_pipeline.py" complete --work-dir <wd>
```

状态摘要、artifact bindings 和构建报告由工具写入，不让模型手工同步。低层图片、OOXML 编辑、原生图表与渲染工具继续使用 `scripts/pptx_tool.py` 及共享 helpers。

## Output contract

交付已确认的 PPTX、预览、PDF或辅助文件；不自动增加类型。工作目录为 `outputs/.pptx-work/<work-id>`，其中的报告属于工作记录。编辑须有 `change-summary.md` 并保持源文件。2.1 的 `presentation_copy` 记录实际标题与标签，冻结语义由主会话自检，精确项由 PPTX 回读检查。

旧 manifest 可用 `status` 读取，不自动迁移或继续执行已删除的子代理管线。需要继续旧成品时，以保留原件的新编辑任务开始。
