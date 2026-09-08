---
name: sp-outline
description: Use only for a clearly student-owned academic context when the user explicitly requests a PPT or slide outline, not an editable deck. Do not use for generic presentations, standalone scripts, Q&A-only work, or non-student tasks.
version: 0.7.0
---

# Student Presentation

规划学生演示文稿，不创建 `.pptx` 文件。

## 快速约束

- 中文正文 ≥ 22pt / 英文正文 ≥ 20pt / 标题 ≥ 24pt
- 每页一条核心信息，≤ 4 条要点，≤ 80 中文字 / 40 英文词
- 避免 AI 套话（"在当今快速发展..."、"具有重要意义..."）
- 使用具体课程/项目背景，直接主张，承认局限
- 按目录→逐页主张→PPT文案→演讲版→Slide Spec 分层生成
- 输出写入 `outputs/`，不得写入 `${CLAUDE_PLUGIN_ROOT}`

## 职责

- 大纲、结构、讲稿 → 本 skill
- 可编辑 PPTX/PowerPoint 文件 → `sp-deck`
- 审查/评分/诊断已有文件 → `sp-review`
- 不得声称能创建 .pptx 文件

## 工作流

1. 加载 `../../references/presentation-intake.md`，使用 outline-only 模式。
2. 加载 `../../references/presentation-brief.md`，分类场景、受众、结构、交互和质量模式。仅确认会影响故事/时间/证据/归属的约束。
3. 按需加载：
   - `references/slide-structures.md` — 结构与主题聚焦
   - `references/transition-phrases.md` — 转场语
   - `references/group-handoff.md` — 小组分工交接
   - `references/qa-prediction.md` — 答辩/汇报 Q&A
   - `../../references/content-workflow.md` — 分层生成流程
   - `../../references/evidence-and-citations.md` — 证据与引用
   - `../../references/revision-training-export.md` — 训练卡/质量报告
   - `../../references/slide-spec.md` — 结构化 PPTX 交接
   - `../../references/image-strategy.md` — 视觉素材策略
4. 宽泛主题时，根据时长和证据提供 2-3 个角度选择。
5. 沿单一主线构建，按序生成：目录→每页主张/要点→PPT文案→演讲版→Slide Spec（用户表明将转 PPTX 时必写）。
6. 每页内容幻灯片提供：故事角色、主张、精简文案、可选视觉、证据引用、讲稿、时间、归属、转场。
7. 新手模式下解释关键结构/布局选择。用 `analyze_presentation_spec.py` 做结构/证据/密度风险检查；需要训练卡、Q&A、词汇表、提词版或修订元数据时运行 `build_support_outputs.py`。
8. 如需文件输出并转 PPTX，先写 `outputs/<topic>-brief.yaml`（按 `../../references/presentation-brief.schema.json`，用 `validate_presentation_brief.py` 校验）与 `outputs/<topic>-slide-spec.yaml`（按 `../../references/slide-spec.schema.json`，用 `validate_slide_spec.py` 校验），把两个文件路径交接给 `sp-deck`；其完整 intake 门禁仍适用。

## 输出契约

使用 `outputs/<topic>-outline.md`、`outputs/<topic>-speaker-notes.md`、`outputs/<topic>-handoff-plan.md`；转 PPTX 时另写 `outputs/<topic>-brief.yaml` 与 `outputs/<topic>-slide-spec.yaml` 作为交接工件。不得写入 `${CLAUDE_PLUGIN_ROOT}`。
