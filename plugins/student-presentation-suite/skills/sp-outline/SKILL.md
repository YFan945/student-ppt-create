---
name: sp-outline
description: Use only for a clearly student-owned academic context when the user explicitly requests a PPT or slide outline, not an editable deck. Do not use for generic presentations, standalone scripts, Q&A-only work, or non-student tasks.
version: 0.10.1
---

# Student Presentation

规划学生演示文稿，不创建 `.pptx` 文件。

## 快速约束

- 中文正文 ≥ 22pt / 英文正文 ≥ 20pt / 标题 ≥ 24pt
- 每页一条核心信息，≤ 4 条要点，≤ 80 中文字 / 40 英文词
- 避免 AI 套话（"在当今快速发展..."、"具有重要意义..."）
- 使用具体课程/项目背景，直接主张，承认局限
- 按目录→逐页主张→PPT文案→演讲版→Slide Spec 分层生成
- 全程遵守 `../../references/cost-discipline.md`：调用并行批量发出、禁止整文件重写、产物写盘即弃、检索一律委派子代理
- 输出写入 `outputs/`，不得写入 `${CLAUDE_PLUGIN_ROOT}`

## 职责

- 大纲、结构、讲稿 → 本 skill
- 外部事实、数据、引用的检索与交叉验证 → `sp-research`（先跑，再排页）
- 可编辑 PPTX/PowerPoint 文件 → `sp-deck`
- 审查/评分/诊断已有文件 → `sp-review`
- 不得声称能创建 .pptx 文件

## 工作流

1. 加载 `../../references/presentation-intake.md`，使用 outline-only 模式。
2. 加载 `../../references/presentation-brief.md`，分类场景、受众、结构、交互和质量模式。仅确认会影响故事/时间/证据/归属的约束。
3. **Research Need Analysis**：动手排页之前先跑 `sp-research`。把待证内容拆成逐条 Claim，判定 A/B/C/D（时效性必须查、会被打分的尽量查、无关的不查、用户限定范围的禁查），由 `sp-research` 产出 `research-pack.json` + passing validation report。不要先写完正文再补来源。D 类时禁止联网，只整理用户材料。
4. 按需加载：`slide-structures.md`、`transition-phrases.md`、`group-handoff.md`、`qa-prediction.md`、`../../references/content-workflow.md`、`../../references/evidence-and-citations.md`、`../../references/research-workflow.md`、`../../references/revision-training-export.md`、`../../references/slide-spec.md`、`../../references/image-strategy.md`。
5. 宽泛主题时，根据时长和证据提供 2-3 个角度选择。
6. 沿单一主线构建，按序生成：目录→每页主张/要点→PPT文案→演讲版→Slide Spec（用户表明将转 PPTX 时必写）。
7. 每页内容幻灯片提供故事角色、主张、精简文案、可选视觉、证据引用、讲稿、时间、归属、转场。研究支持的 **draft Slide Spec** 在 `evidence_refs` 中直接使用 Research Pack 的 `F/D/Q` id；不要生成 `E<n>`、不要手写 Research Evidence Ledger。`confidence: low` 或 conflict 条目必须写成区间/限定语。`sp-deck` 后续由 `research_pack_to_evidence.py` 机械编译为 E ids、ledger 与 `used_on_slides`。
8. 新手模式下解释关键结构/布局选择。用 `analyze_presentation_spec.py` 做结构/证据/密度风险检查；需要训练卡、Q&A、词汇表、提词版或修订元数据时运行 `build_support_outputs.py`。
9. 如需文件输出并转 PPTX，写 `outputs/<topic>-brief.yaml` 与 **draft** `outputs/<topic>-slide-spec.yaml`，分别按 schema 校验；将 Brief、draft spec、Research Pack 和 research validation 路径一起交给 `sp-deck`。最终冻结的是 `sp-deck` 编译出的 Slide Spec，不是这份 draft。

## 输出契约

使用 `outputs/<topic>-outline.md`、`outputs/<topic>-speaker-notes.md`、`outputs/<topic>-handoff-plan.md`；转 PPTX 时另写 `outputs/<topic>-brief.yaml` 与 draft `outputs/<topic>-slide-spec.yaml`。不得写入 `${CLAUDE_PLUGIN_ROOT}`。
