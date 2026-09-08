---
name: sp-review
description: Use only for a clearly student-owned academic context when the user explicitly asks to review, audit, score, critique, compare, or diagnose an existing PPT/PPTX/PowerPoint deck or rendered export.
version: 0.7.1
---

# Student Presentation Review

审查已有学生演示文稿。默认只诊断和建议，不修改文件。

## 快速约束

- 中文正文 ≥ 22pt / 英文正文 ≥ 20pt / 标题 ≥ 24pt
- 每页 ≤ 4 条要点，≤ 80 中文字 / 40 英文词
- 避免 AI 套话；检查重复句式、空泛过渡、夸大主张
- 分级：Critical（阻断理解/评分/表达）、Major（应修复）、Minor（润色）
- 静态 XML 风险是信号，不替代渲染检查
- 视觉结论需要渲染证据支撑
- 输出写入 `outputs/`，不得修改源文件

## 职责

- "看看问题"、审查、评分、诊断 → 本 skill（只读）
- "直接改好"、修改、重建 → 先诊断，再交接给 `sp-deck`（生成独立改进版 + change summary + revision manifest）
- 不得覆盖原始 deck

## 工作流

1. 加载 `../../references/presentation-intake.md`，使用 review-only 模式。
2. 按需加载：
   - `references/review-checklist.md` — 审查维度与严重度
   - `references/review-output-format.md` — 报告格式
   - `../../references/content-workflow.md` — 故事顺序检查
   - `../../references/evidence-and-citations.md` — 来源缺口
   - `../../references/revision-training-export.md` — 逐页评分与演练
   - `../../references/slide-spec.md` — 计划与实际对比
   - `../../references/image-strategy.md` — 视觉/来源审查
3. 对 PPTX 输入运行 `pptx_static_check.py <deck.pptx> --json`。
4. 检查渲染预览、PDF 页面、截图或 contact sheet。只有 PPTX 而无预览时，调用
   `python "${CLAUDE_PLUGIN_ROOT}/scripts/pptx_tool.py" render <deck.pptx> --output-dir <work-render-dir> --prefix <topic>`；
   渲染不可用则结论必须为 `incomplete`。渲染证据决定裁剪和可读性结论。
5. 每次发现分级为 Critical / Major / Minor，记录 `target`（目标页面/页码）、`problem`（问题+影响）、`fix`（具体修复建议），与 `review_findings` schema 一致。
6. 检查来源缺口、故事顺序、重复页面、结论支撑、时间、转场、开篇/收尾、可能的问题。有 Slide Spec 时运行 `analyze_presentation_spec.py`。
7. 编辑请求时，写 `outputs/<topic>-slide-spec.yaml`（含 `source_deck`、`edit_intent`、`review_findings`（`severity`/`target`/`problem`/`fix`）、`preserve`、`change_summary_required`，按 `../../references/slide-spec.schema.json` 校验），再进入 `sp-deck`。

交接说明：编辑交接件 `slide-spec.yaml` 是诊断与编辑意图的结构化输入，不等于生产授权。
进入 `sp-deck` 后复用所有已知事实，不重复询问，但仍须展示一次完整 Production Summary
并记录确认 hash；review 交接可豁免单独 Presentation Brief 文件，不能豁免确认门禁。

## 评审结论标签

`complete` / `incomplete` / `blocked` 是评审报告的结论标签，仅描述审查完成度；
本 skill 不调用 `workflow_guard.py`，不写 `.student-presentation-state.json`。

- 静态扫描 + 渲染检查完成 → `complete`
- 审查有用但缺少渲染证据 → `incomplete`；声明视觉结论未经核实
- 必需产物无法读取 → `blocked`

不得将静态 XML 输出当作渲染溢出或可读性的证明。不得声称能预测 AI 检测器结果。

## 输出契约

评审报告默认写入 `outputs/<topic>-review.md`；编辑交接件写入 `outputs/<topic>-slide-spec.yaml`。
写入 `${CLAUDE_PROJECT_DIR}/outputs` 或当前项目的 `outputs/` 回退，不得写入 `${CLAUDE_PLUGIN_ROOT}`。
