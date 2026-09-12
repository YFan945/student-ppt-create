# Presentation Intake

This is the canonical intake contract for student presentation work. Reuse facts
already supplied by the user, attached materials, an existing deck, or Slide
Spec meta. Never ask for a confirmed item again.

## Intake Modes

- PPTX creation or existing-deck editing: full intake is a hard gate.
- Outline-only planning: ask only for missing items that materially change the
  story, timing, evidence, or ownership; low-risk preferences may be stated as
  assumptions.
- Review-only work: proceed when the artifact is readable; ask only for missing
  duration, presentation type, group format, or rubric when it materially
  changes the review.

Use `presentation-brief.md` for scenario classification, audience depth,
interaction mode, quality level, structure mode, and generation controls.
`beginner` mode explains recommendations; `expert` mode asks only unresolved
high-impact decisions. Both modes keep the full PPTX confirmation gate.

## Full PPTX Intake

Confirm every item before production:

| Item | Recommended value when missing | Why it matters |
| --- | --- | --- |
| Topic | Restate the user's topic as one focused sentence | Defines the story and slide claims |
| Course/context | General undergraduate classroom report | Controls terminology and academic framing |
| Presentation type | Coursework report | Determines required sections |
| Audience | Teacher and classmates | Controls explanation depth |
| Scenario | Coursework | Selects scoring and story defaults |
| Audience depth | Standard | Controls terminology and explanation |
| Language | Follow the user's language | Controls slide and note language |
| Duration | 5 minutes | Controls scope and timing |
| Slide count | 7-9 slides for 5 minutes | Controls density |
| Format | Individual unless members are named | Controls ownership and handoffs |
| Rubric/required sections | No supplied rubric; use standard academic structure | Controls scoring priorities |
| Source material | User material plus stable general background | Controls evidence boundaries |
| Template/branding | No required template, logo, or brand | Controls layout constraints |
| Source deck (新建/改进) | No existing deck → create new | Decides `production_mode`: an editable `.pptx`/`.potx` source → `edit_ooxml`; a corrupt source or non-PPTX (PDF/preview) → `rebuild_from_source`/`create`; otherwise `create` |
| Edit intent | None (new deck) | For improvements: `incremental` / `rebuild-clean-copy` / `fix-specific`; `rebuild-clean-copy` overrides the edit_ooxml default |
| Image strategy | `hybrid-adaptive`：生成能力可用且获准时制作关键插图，否则采用确定性图表/形状 | Controls sourcing and production |
| Visual style | Recommend three topic-fit styles; choose one only after confirmation | Controls visual direction |
| Deliverables | PPTX, speaker notes, preview/contact sheet; add change summary for edits | Controls completion criteria |
| Interaction/quality mode | Beginner + high-score | Controls guidance, evidence, and rehearsal depth |
| Structure mode | Scenario default | Controls the narrative spine |
| Content controls | 40 English words / 80 Chinese characters, balanced visual/text, notes on | Controls density and output layers |
| Citation/export/versioning | Classroom citations; requested local exports; versioning on for edits | Controls traceability and rollback |

If duration is known but slide count is not, recommend:

- 3 minutes: 5-7 slides
- 5 minutes: 7-9 slides
- 8 minutes: 9-12 slides
- 10 minutes: 10-14 slides
- 15 minutes: 14-18 slides

## Required Interaction

For an incomplete PPTX request, use `AskUserQuestion` to let the user select
each unresolved field directly — one question per field, with recommended values
as the first option. Do NOT list all fields in text and ask for a consolidated
reply.

### Interaction flow

1. Extract all already-confirmed facts from the user's request; display them as
   `✅ 已确认` in a short summary.
2. Identify unresolved fields that have clear option sets. Batch them into
   `AskUserQuestion` calls (max 4 questions per call, 2-4 options each).
3. For each question, the first option is always the recommended value, labeled
   with `（推荐）`. Include a one-line impact statement in each option's
   `description`.
4. After the user selects, move to the next batch of unresolved fields. Repeat
   until all fields are resolved.
5. If the user types “你决定”, “按推荐来”, or “use the recommendations” at any
   point, stop asking and fill all remaining fields with recommended values.
6. After all fields are resolved, show the complete `Production Summary` and ask
   for final confirmation **via `AskUserQuestion`**（不要以纯文本收尾等待自由输入）。
   Delegation does NOT itself move the state to `intake_confirmed`; approval of
   the summary does. 确认选项固定为：
   - `确认，开始制作（推荐）` → 批准摘要并进入生产
   - `调整方案` → 修改页数/配色/内容后重新确认
   - `更换视觉风格` → 回到风格选择（Round 3a）重新选
   - `Other`（自由输入，例如"改为仅大纲"）
   用户选中"确认"后，才调用 `confirm --summary-file <summary>` 落 `intake_confirmed`。
7. 任何一轮询问之后需要用户表态时，一律用 `AskUserQuestion` 继续，不要以纯文本
   收尾中断会话。
8. Do not run environment checks, generation scripts, rendering, or delivery
   checks while the state is `intake_pending`.
9. If a field has no natural option set (e.g. Topic, Course/context, Rubric),
   use `AskUserQuestion` with `”Other”` as a free-text fallback, or ask inline.

### Question batches (by priority)

Batch fields so that the most impactful decisions come first. Typical grouping:

**Round 1 — 场景与受众** (pick the ones that are unresolved):
- `Presentation type` → options: Coursework report, Defense/答辩, Competition/竞赛, Club showcase, Research paper
- `Scenario` → options from scenario classification table
- `Audience` → options: Teacher + classmates, Non-specialists, Judges/Panel, Mixed
- `Audience depth` → options: Introductory, Standard, Expert

**Round 2 — 规模与格式**:
- `Duration` → options: 3min (5-7页), 5min (7-9页), 8min (9-12页), 10min (10-14页), 15min (14-18页)
- `Format` → options: Individual/个人, Group/小组 (2-4人), Group/小组 (5+人)
- `Interaction mode` → options: Beginner/新手引导, Expert/专家模式

`Quality level` 不再询问：默认 `High-score/高分`（仅在用户明确要求低要求时才降为
Basic）。`Citation style` 不再询问：默认 `Classroom/课堂引用`，内容中不强调引用风格。

**Round 3 — 视觉与素材**:
- `Visual style` → **两步选择**:
  - **Step A — 风格类别**：根据 topic 将最匹配的类别放在第一个选项并标注
    `（推荐）`，一次提供以下四个选项：
    - 学术与专业类：Academic Rigorous、Data Driven、Modern Minimal、Charcoal Editorial
    - 商务与科技类：Midnight Business、Ocean Tech、Teal Trust、Cherry Bold
    - 创意与人文类：Creative Student、Coral Energy、Forest Moss、Warm Terracotta
    - 其他：用户自由描述视觉方向
  - **Step B — 具体样式**：仅当用户选择前三类时，一次显示该类全部 4 种，
    根据 topic 标注一个最佳推荐。不要再提供“显示全部”、跨类别或分轮入口。
  - 用户选择“其他”时不进入 Step B。根据主题和用户描述补齐
    `visual_style_custom` 的四项结构：`style_character`、六角色 `palette`、
    `backgrounds`（cover/content/section/closing）和 `svg_reference`（name/usage）。
    Production Summary 必须完整展示这四项；未展示并确认前不得进入 `planned`。
- `Image strategy` → options:
  - `自适应混合（推荐）` → 生成能力可用且获准时制作关键插图；否则自动采用图表、原生形状或文字构图，不因缺少外部生图工具阻断生产
  - `内置生图 skill 生成插图` → 全部插图（含封面/背景/概念图）由 imagegen 生成
  - `Diagram-only/仅图表` → 仅图表与原生形状，无外部依赖，最安全最快
  - `Web image/联网图片` → 真实人物/地点/产品等先确认是否允许联网搜图
  - `User-provided image/用户照片` → 优先使用用户提供的素材
  - `Ask-before-web-search/每次联网前询问`
  - `No images/无图` → 纯图表/形状/文字版式
  - 选项可用性以当前会话解析出的 image capability 为准：`image_generation_ready` 为 false
    时不得提供"内置生图 skill 生成插图"为可兑现项，`image_search_ready` 为 false 时不得
    承诺联网搜图；声明机制与降级见 `../../references/image-sourcing.md`。
- `Citation style` → 不询问，默认 `Classroom/课堂引用`（详见 `../../references/evidence-and-citations.md`）
- Round 3 只有视觉风格（占 2 轮）与配图 1 个问题，若需要可把 Deliverables 提前到本轮填满槽位

**Round 4 — 输出格式**:
- `Deliverables` (multi-select) → options: PPTX/幻灯片, Speaker notes/讲稿, Preview/预览图, PDF export/PDF, Contact sheet/缩略图联系人表, Full script/完整演讲稿
- Other output-specific fields as needed

### Example

```
已确认：Topic=深度学习入门, Language=中文, Source material=课程讲义

→ 调用 AskUserQuestion（Round 1，4 个问题）让用户选择：
  1. Presentation type → Coursework report（推荐）
  2. Scenario → coursework
  3. Audience → Teacher + classmates（推荐）
  4. Audience depth → Standard（推荐）

→ 用户选择后，调用 AskUserQuestion（Round 2）：
  1. Duration → 5min（推荐）
  2. Format → Individual（推荐）
  3. Interaction mode → Beginner（推荐）
  （Quality level 不再询问，默认 High-score/高分）

→ 用户选择后，调用 AskUserQuestion（Round 3a — 风格类别）：
  1. 风格类别 → 商务与科技类（推荐）/ 学术与专业类 / 创意与人文类 / 其他

→ 用户选"商务与科技类"后，调用 AskUserQuestion（Round 3b — 具体样式与配图）：
  1. Visual style → Ocean Tech 海洋科技（推荐）/ Midnight Business 午夜商务 /
     Teal Trust 青绿可信 / Cherry Bold 樱桃醒目
  2. Image strategy → 生图+SVG/原生形状结合（推荐）/ Diagram-only 仅图表 / 内置生图 skill / Web image / ...
  （Citation style 不再询问，默认 Classroom）

→ 所有字段确认完毕，展示完整 Production Summary，用 AskUserQuestion 请求最终确认：
  1. 是否按以上方案开始制作？ → 确认，开始制作（推荐）/ 调整方案 / 更换视觉风格 / Other
```

### Delegation shortcut

If the user says “你决定”, “按推荐来”, or “use the recommendations” at any
point, fill every remaining unresolved field with the recommended value. Then
show the complete `Production Summary` and ask for explicit confirmation **via
`AskUserQuestion`**（选项见 Interaction flow 步骤 6，勿以纯文本收尾）。

If all fields were already supplied in the initial request, skip the question
rounds and go directly to showing the complete `Production Summary` for
confirmation.

## Production Summary

The confirmation summary must list all full-intake fields plus the planned output
directory or filename prefix when known. Only an affirmative reply to this
summary moves the workflow to `intake_confirmed`. 确认必须通过 `AskUserQuestion`
（选项：确认，开始制作 / 调整方案 / 更换视觉风格 / Other），不要以纯文本
"回复确认即可开始"这类方式中断会话等待自由输入。

After confirmation, map supported values into Slide Spec `meta`:

- `topic`, `presentation_type`, `audience`, `language`, `duration_min`, `slide_count`
- `scenario`, `audience_type`, `audience_depth`, `structure_mode`
- `interaction_mode`, `quality_level`, `max_words_per_slide`,
  `max_chinese_chars_per_slide`, `visual_text_ratio`
- `include_speaker_notes`, `include_key_lines`, `citation_style`,
  `export_formats`, `versioning`
- `format`, `members`, `course`, `rubric`
- `source_material`, `template`, `logo`, `image_source`, `visual_style`
- `visual_style_custom`（仅 `visual_style: Other` 或兼容旧未知风格时使用）
- `deliverables`, `output_prefix`

Use existing-deck top-level fields for editing: `source_deck`, `edit_intent`,
`review_findings`, `preserve`, and `change_summary_required`.

For complex or file-producing work, save the confirmed global controls as a
Presentation Brief and validate it before creating the Slide Spec. Do not ask
the user to approve both documents separately when the Slide Spec faithfully
implements the already approved summary.

## Workflow States

`intake_pending → intake_confirmed → planned → producing → qa → complete`

- `intake_pending`: full intake is incomplete or its summary is unconfirmed.
- `intake_confirmed`: user approved the complete Production Summary.
- `planned`: slide spine or Slide Spec is ready.
- `producing`: editable files are being generated or edited.
- `qa`: package validation, optional rendering/inspection, and delivery checks run.
- `complete`: all required deliverables and gates passed.
- `incomplete`: a usable artifact exists but a required deliverable or QA gate failed.
- `blocked`: production cannot proceed because a required input, artifact, or runtime dependency is unavailable.

The rework edge is `qa → producing` (with `--reason <blocker summary>`), used to
rebuild after a QA blocker is found without restarting the whole pipeline. The
recovery edge is `incomplete → qa` (with `--reason <summary>`), used to re-enter
QA after a missing gate or runtime dependency is resolved; `blocked` recovers via
`unblock`, which returns to `intake_pending` and requires re-confirmation. Never
claim production has started before `intake_confirmed`. `incomplete` and `blocked`
may be entered from any later state when their conditions are met.

For PPTX work, persist this state under the active project with
`scripts/workflow_guard.py`. The workflow gate is tracked through the state
commands as a process convention; the summary file hash is retained as the
auditable confirmation boundary.
