---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.7.0
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；
编辑请求由 `sp-review` 诊断后以结构化交接（`outputs/<topic>-slide-spec.yaml`）进入本 skill 的编辑分支。

## Canonical references

- 始终加载 `../../references/presentation-intake.md` 和 `../../references/shared-standards.md`。
- 规划时加载 `../../references/content-workflow.md`、`../../references/slide-spec.md`、`../../references/image-strategy.md` 和 `references/pptx-production.md`。
- 视觉选择加载 `references/visual-style-menu.md`，确认后只加载一个 `references/visual-styles/<style>.md`；执行视觉系统时必须加载 `references/pptx-design-grammar.md` 和 `references/pptx-visual-engine.md`。
- 需要引用时加载 `../../references/evidence-and-citations.md`；编辑或版本控制时加载 `../../references/revision-training-export.md`。
- 低层命令、安全规则、编辑和 QA 分别由 `references/pptx-runtime.md`、`references/pptxgenjs-safety.md`、`references/pptx-editing.md`、`references/pptx-qa.md` 负责。

## State gate

状态按
`intake_pending → intake_confirmed → planned → producing → qa → complete`
正向推进，终态为 `incomplete` 或 `blocked`。`qa → producing` 是一次正式返工边；该正式返工内部允许最多 3 个受控 render-repair iterations。`incomplete → qa` 用于补齐缺失门禁后重入 QA，均须带 `--reason <摘要>`。

状态命令统一为：

```bash
python "${CLAUDE_PLUGIN_ROOT}/scripts/workflow_guard.py" <init | confirm --summary-file <summary> | transition --to <state> [--reason <摘要>]>
# 完成：transition --to complete --pptx <pptx> --delivery-report <report>
```

确认前只允许读取用户材料和收集需求，不得检查环境、生成、编辑、渲染或交付。必须让用户明确批准完整 Production Summary，再调用 `confirm --summary-file <summary>`。

## Workflow

1. **Intake**：按 `references/presentation-intake.md` 完成需求收集；展示完整 Production Summary 并请求确认。用户说“你决定”只采用推荐值，仍须确认摘要。
2. **判定模式**：根据 `source_deck`/`edit_intent` 确定唯一 `production_mode`（`create` / `edit_ooxml` / `rebuild_from_source`），规则见 `references/pptx-production.md`。
3. **规划**：验证 Presentation Brief 与 Slide Spec；内容分析默认作为建议，但来源不可追溯、未知 evidence ref、结构无效和 rubric 明确遗漏必须修正。确定 mode 后运行严格环境检查，再转为 `planned`。
4. **Design Grammar**：根据 presentation type 选择 `pptx-design-grammar.md` 中最接近的场景语法。visual style 负责气质，design grammar 负责页面语言和整套节奏，layout catalog 只作为 inspiration/fallback。允许 `visual_strategy: typography`，不得因 high-score 模式强塞图片或图标。
5. **生产**：转为 `producing`。create/rebuild 默认使用完整 `deck.js` 做 adaptive-freeform，但每个真实 text/shape/image/chart/line 必须登记进 `scripts/pptx-element-registry.js`；`registry.assertSafe()` 必须在写入 PPTX 前通过。composer/版式库仅用于锁定、兼容、灵感或失败兜底；edit_ooxml 继续走解包/修改/clean/pack。
6. **Actual Artifact Check**：candidate 写盘后先用 `${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py validate` 做 package validation，再运行 `skills/sp-deck/scripts/pptx_actual_content_check.py --strict`，直接回读最终 PPTX 与 Slide Spec 对比页数、标题、key claim、显式 slide_copy 与关键数字。generator/spec 声称存在但最终 PPTX 丢失的内容属于 blocker。
7. **Render-conditioned QA**：转为 `qa`，完整渲染全部页面并逐页观察真实 artifact。检查裁切、溢出、重叠、字体 fallback、低对比、图片裁切、层级、视觉焦点、页面节奏、filler visual、明显内容漂移和可直接观察的 rubric 要求。发现 blocker 后进入一次正式 `qa → producing` 返工，在该返工内部允许最多 3 个 `render → critique → revise → rebuild → validate/readback → render` iterations；每轮必须收敛，第 3 次后仍有 blocker → `incomplete`。
8. **支持产物/版本**：`build_support_outputs.py` 仅按已确认 deliverables 生成 notes/script/teleprompter/training cards/references；编辑任务生成 change summary 与 revision manifest。所有模式输出新文件，禁止覆盖 source deck。
9. **完成**：PPTX、Slide Spec validation、package validation、actual-content check、完整预览和 visual review 全部通过后运行 simplified strict delivery check，再 `transition --to complete --pptx <pptx> --delivery-report <report>`。缺渲染或用户放弃时只能 `incomplete`。

## Generation core contract

默认 create/rebuild 核心链路固定为：

```text
Production Summary
  → Presentation Brief / Slide Spec
  → Design Grammar
  → Per-slide Composition Intent
  → Model-authored native PptxGenJS elements
  → Actual Element Registry static analysis
  → PPTX package validation
  → PPTX artifact readback vs Slide Spec
  → Full render
  → Vision/visual critic
  → Controlled repair loop
  → Delivery
```

这里的关键原则是：

- 模型负责“表达什么、视觉焦点是什么、采用何种构图语言”；
- runtime 负责“真实元素是否越界/重叠/溢出，实际 PPTX 是否与计划一致”；
- render critic 负责“最终页面是否真的好看、清楚、像人设计的”；
- 不再把 advisory composition preflight 或一个 `--visual-reviewed` 布尔值视为完整质量证明。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`：PPTX、speaker notes、逐页 preview/contact sheet、package report、`actual-content-report.json`、delivery report，以及编辑任务的 change summary 与 `outputs/<topic>-slide-spec.yaml`。中间文件放在 `outputs/.pptx-work/<work-id>/`。

交付完成后提示用户可运行 `sp-review` 做只读复核/评分。最终回复报告所有绝对路径、页数、package validation、actual-content check、visual QA、交付状态和剩余限制。
