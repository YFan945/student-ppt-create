---
name: sp-deck
description: Use only for a clearly student-owned academic context when the user explicitly asks to create, edit, improve, or rebuild an editable PPT, PPTX, PowerPoint, or slide deck.
version: 0.7.1
---

# Student Presentation PPT

创建或改进可编辑的学生学术 PPTX。仅大纲走 `sp-outline`；只读审查/诊断走 `sp-review`；
编辑请求由 `sp-review` 诊断后以结构化交接（`outputs/<topic>-slide-spec.yaml`）进入本 skill 的编辑分支。

## Canonical references

- 始终加载 `../../references/presentation-intake.md` 和 `../../references/shared-standards.md`。
- 规划时加载 `../../references/content-workflow.md`、`../../references/slide-spec.md`、`../../references/image-strategy.md` 和 `references/pptx-production.md`。
- 视觉选择加载 `references/visual-style-menu.md`，确认后只加载一个 `references/visual-styles/<style>.md`；执行视觉系统时必须加载 `references/pptx-design-grammar.md`、`references/pptx-visual-engine.md` 和 `references/pptx-visual-critic.md`。
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
3. **规划 + Freeze**：验证 Presentation Brief 与 Slide Spec；内容分析默认作为建议，但来源不可追溯、未知 evidence ref、结构无效和 rubric 明确遗漏必须修正。验证报告通过后，必须用 `skills/sp-deck/scripts/slide_spec_guard.py freeze` 绑定 Slide Spec 与 validation report 的 SHA-256，再转为 `planned`。从此禁止静默修改 plan。
4. **Design Grammar**：根据 presentation type 选择 `pptx-design-grammar.md` 中最接近的场景语法。visual style 负责气质，design grammar 负责页面语言和整套节奏，layout catalog 只作为 inspiration/fallback。允许 `visual_strategy: typography`，不得因 high-score 模式强塞图片或图标；typography 不得只是编号列表换皮。
5. **生产**：进入 `producing` 前先运行 `slide_spec_guard.py check`。create/rebuild 默认使用完整 `deck.js` 做 adaptive-freeform，但每个真实 text/shape/image/chart/line 必须登记进 `scripts/pptx-element-registry.js`；`registry.assertSafe()` 必须在写入 PPTX 前通过。composer/版式库仅用于锁定、兼容、灵感或失败兜底；edit_ooxml 继续走解包/修改/clean/pack。
6. **Actual Artifact Check**：candidate 写盘后再次检查 frozen spec；先用 `${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py validate` 做 package validation，再运行 `skills/sp-deck/scripts/pptx_actual_content_check.py --strict`，直接回读最终 PPTX 与**冻结的** Slide Spec 对比页数、标题、key claim、显式 slide_copy 与关键数字。readback 失败默认修 `deck.js` / actual PPTX，禁止通过改 Slide Spec 让检查通过。
7. **显式 Spec Revision（仅必要时）**：只有计划本身确实错误、用户需求变化或事实/结构问题要求改计划时，才允许修改 Slide Spec；修改后必须重新运行 validator，再调用 `slide_spec_guard.py revise --reason <原因>`。revision 会保留 parent hash；之后必须重新生成受影响 artifact。它不是普通 render repair 手段。
8. **Render-conditioned QA**：转为 `qa`，完整渲染全部页面并逐页观察真实 artifact；按 `pptx-visual-critic.md` 写绑定当前 PPTX hash 的 `visual-review.json`。除了裁切/溢出/字体等工程问题，还必须给每页的 hierarchy、focal point、composition、visual interest、whitespace 打分，记录 `visual_structure`、AI-template feel 与 unresolved findings。
9. **v0.7.1 Quality Gate**：运行 `pptx_quality_gate_v071.py --strict`，同时检查 structured visual critic、deck-level rhythm、Evidence Closure 与 speaker timing。High-score 单项视觉分低于 6、整套平均低于 7、连续两页弱卡片/列表结构、未闭环引用、整体讲稿预计超时 15% 等 Major/Critical 均阻断。发现 blocker 后进入一次正式 `qa → producing` 返工，在该返工内部允许最多 3 个 `render → critique → quality gate → revise artifact → rebuild → validate/readback → render` iterations；每轮必须收敛，第 3 次后仍有 blocker → `incomplete`。
10. **支持产物/版本**：`build_support_outputs.py` 仅按已确认 deliverables 生成 notes/script/teleprompter/training cards/references；编辑任务生成 change summary 与 revision manifest。所有模式输出新文件，禁止覆盖 source deck。
11. **完成**：PPTX、Slide Spec validation + lock、package validation、actual-content check、完整预览、structured visual review 与 `quality-report.json` 全部通过后，运行 `pptx_delivery_check_v071.py --strict --visual-reviewed`，再 `transition --to complete --pptx <pptx> --delivery-report <report>`。缺渲染、quality gate blocker 或用户放弃时只能 `incomplete`。

## Generation core contract

默认 create/rebuild 核心链路固定为：

```text
Production Summary
  → Presentation Brief / Slide Spec
  → Validate + Freeze Slide Spec
  → Design Grammar / Per-slide Composition Intent
  → Model-authored native PptxGenJS elements
  → Actual Element Registry static analysis
  → PPTX package validation
  → PPTX artifact readback vs frozen Slide Spec
  → Full render
  → Structured Vision/visual critic
  → Rhythm + Evidence + Timing quality gate
  → Controlled artifact repair loop
  → Delivery
```

这里的关键原则是：

- 模型负责“表达什么、视觉焦点是什么、采用何种构图语言”；
- frozen Slide Spec 负责定义不可被 candidate 反向篡改的 production plan；
- runtime 负责“真实元素是否越界/重叠/溢出，实际 PPTX 是否与计划一致”；
- render critic 负责“最终页面是否真的好看、清楚、像人设计的”；
- quality gate 负责“整套视觉节奏、引用闭环和真实讲述时长是否达到交付标准”；
- 不再把 advisory composition preflight、单独的 `--visual-reviewed` 布尔值或“无 overflow/overlap”视为完整质量证明。

## Output contract

仅写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目 `outputs/`：PPTX、speaker notes、逐页 preview/contact sheet、package report、`actual-content-report.json`、`visual-review.json`、`quality-report.json`、delivery report，以及编辑任务的 change summary 与 `outputs/<topic>-slide-spec.yaml`。中间文件放在 `outputs/.pptx-work/<work-id>/`，其中必须保留 `slide-spec-lock.json` 作为 plan freeze 证据。

交付完成后提示用户可运行 `sp-review` 做只读复核/评分。最终回复报告所有绝对路径、页数、package validation、actual-content check、quality gate、visual QA、交付状态和剩余限制。