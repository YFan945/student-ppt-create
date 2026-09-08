---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.6.0
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；
编辑请求由 `sp-review` 诊断后以结构化交接（`outputs/<topic>-slide-spec.yaml`）进入本 skill 的编辑分支。

## Canonical references

- 始终加载 `../../references/presentation-intake.md` 和 `../../references/shared-standards.md`。
- 规划时加载 `../../references/content-workflow.md`、`../../references/slide-spec.md`、
  `../../references/image-strategy.md`、`references/design-grammar.md` 和 `references/pptx-production.md`。
- 视觉选择加载 `references/visual-style-menu.md`，确认后只加载一个
  `references/visual-styles/<style>.md`；执行视觉系统加载 `references/pptx-visual-engine.md`。
- 需要引用时加载 `../../references/evidence-and-citations.md`；编辑或版本控制时加载
  `../../references/revision-training-export.md`。
- 低层命令、安全规则、编辑和 QA 分别由 `references/pptx-runtime.md`、
  `references/pptxgenjs-safety.md`、`references/pptx-editing.md`、`references/pptx-qa.md` 负责。

## State gate

状态按
`intake_pending → intake_confirmed → planned → producing → qa → complete`
正向推进，终态为 `incomplete` 或 `blocked`；返工边 `qa → producing` 用于视觉/内容 blocker 修复，
恢复边 `incomplete → qa` 用于补齐缺失门禁后重入 QA，均须带 `--reason <摘要>`。

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" <init | confirm --summary-file <summary> | transition --to <state> [--reason <摘要>]>
```

确认前只允许读取用户材料和收集需求，不得生成、编辑、渲染或交付。必须让用户明确批准完整
Production Summary，再调用 `confirm --summary-file <summary>`。

## Workflow

1. **Intake**：按 `presentation-intake.md` 收集需求；展示完整 Production Summary 并请求确认。
2. **判定模式**：根据 `source_deck`/`edit_intent` 确定唯一 `production_mode`
   （`create` / `edit_ooxml` / `rebuild_from_source`）。
3. **规划**：验证 Presentation Brief 与 Slide Spec；内容分析默认建议性，但 evidence ref、结构错误、
   关键 rubric 约束必须先修复。将 `layout` 视为功能意图，不视为默认锁定模板。
4. **设计决策**：先按 `design-grammar.md` 决定全套叙事节奏、页面类型分布和视觉母题，再逐页确定
   composition。允许高质量 `typography` / text-led 页面，不得为了视觉配额强塞图标、卡片或无关图片。
5. **生产**：转为 `producing`。create 默认采用 adaptive-freeform PptxGenJS；共享 layout/composer
   用于建议、锁定、兼容和 deterministic fallback。模型负责语义层级、视觉焦点和比例，所有最终
   元素必须落入可检查的实际 PPTX artifact；不得把 preflight composition 当作最终真实性证明。
6. **Artifact QA + Render-Reflect**：转为 `qa` 后，对最终 PPTX 依次执行：
   - package validation；
   - `pptx_static_analyzer.py` 检查真实 PPTX 元素的画布、重叠和 text-fit 风险；
   - `pptx_plan_check.py` 对照 Slide Spec 检查标题、页数、关键数字和 claim 漂移；
   - 完整渲染全部页面；
   - 逐页视觉复审，检查裁切、溢出、低对比、视觉层级、留白、比例、图表/图片质量与 rubric fit。
7. **修复闭环**：发现 blocker/major 时，记录 findings，回到 `producing` 修改 spec/composition/generator，
   重新生成完整 candidate，再从静态分析、plan-vs-actual、package、render、visual review 全部重跑。
   Render 是生成算法的一部分，不只是最后门禁。禁止只修改 delivery flag 来宣称通过。
8. **编辑/版本**：编辑任务生成 change summary 与 revision manifest；source deck 保持只读。
9. **完成**：当前 PPTX 与 delivery report hash 绑定，规划一致性、package、真实 artifact 静态分析、
   全页 preview 和视觉复审均无 blocker 后才能 `complete`。缺渲染能力只能 `incomplete`。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目的 `outputs/`：PPTX、speaker notes、逐页 preview/
contact sheet、package report、static layout report、plan-vs-actual report、delivery report，以及编辑任务的
change summary 与 `outputs/<topic>-slide-spec.yaml`。中间文件放在 `outputs/.pptx-work/<work-id>/`。
最终回复报告绝对路径、页数、package validation、static analysis、plan-vs-actual、visual QA、交付状态和剩余限制。
