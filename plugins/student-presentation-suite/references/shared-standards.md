# Shared Student Presentation Standards

For new tasks, [model-led design](model-led-design.md) owns creative freedom and verification. Existing tasks retain their frozen controls.

Use these standards across research, planning, PPTX production, and review.

## Canonical Ownership

This file is the canonical source for suite-wide routing, typography, density,
language-level defaults, anti-AI wording, and group-presentation rules. Skill
files should describe task-specific workflow and link here instead of redefining
suite-wide thresholds. `presentation-intake.md` owns clarification and workflow
states, `presentation-brief.md` owns global scenario/audience/control semantics,
`slide-spec.md` owns structured handoff rules, `image-strategy.md`
owns source/visual policy, `research-workflow.md` owns when and how external
knowledge is gathered (A/B/C/D classification, source tiers, cross-validation,
and the Research Pack contract), and `cost-discipline.md` owns how the
work is carried out: batched independent calls, focused page repairs,
main-session production, isolated factual research and observational usage reports.

## Intent Routing

Before routing to any skill in this suite, require both a clear student-owned academic context and an explicit PPT-related intent. Strong context includes an identified student, university assignment, classroom report, thesis/course defense, teacher rubric, or student competition. Do not treat a single ambiguous word such as "course", "class", "competition", or "defense" as sufficient without supporting academic cues. PPT-related intent must be one of: requesting a PPT/slide outline; requesting PPT/PPTX creation or improvement; requesting review of an existing PPT artifact; or requesting external facts, current data, statistics, citations, or a Research Pack that will support such a deck (including user-material-only scope D). Do not use this suite for generic presentation work, standalone scripts/Q&A, attached decks without a review request, or non-student presentations.

Choose the skill by the user's requested outcome, not only by the input type:
- Use `sp-research` when an eligible student-context request needs external facts, current data, statistics, citations, or a Research Pack. Scope D (user's own materials) defaults to `sp-outline`'s deterministic `import_user_materials.py` import with no subagent; it reaches `sp-research` only when the user explicitly asks the researcher to organize the materials. `sp-research` never designs slides or creates PPTX.
- Use `sp-outline` when an eligible student-context request explicitly asks for a PPT/slide outline or Slide Spec outline handoff.
- Use `sp-deck` when the user asks for PPT, PPTX, PowerPoint, slides, editable deck, rendered preview, or a ready presentation file.
- Use `sp-review` when the user provides an existing artifact and asks for review, scoring, risk checks, before/after comparison, or improvement advice.

Ambiguous requests:
- "做一个 PPT", "生成 slides", "make a slide deck", "make PowerPoint", or "make PPTX" means PPTX production unless the user explicitly says outline only.
- "prepare a presentation" or "help me present" without explicit student context and PPT wording is outside this suite.
- "PPT 大纲" or "slide outline" in an explicit student context means planning, not file generation, unless the user also asks for `.pptx`.
- "帮我查证/找来源/补引用/这些数据从哪来" in an explicit student PPT context means `sp-research`, even when the user has not yet asked for an outline or a `.pptx`.
- "帮我看看/审一下/打分/有什么问题" with an existing artifact means review.
- "帮我优化这个 PPT" with an existing artifact means first review and identify fixes; only edit or regenerate the deck if the user explicitly asks for file changes.
- A broad topic with no explicit student context and PPT output target is outside this suite.
- If a request mixes planning and PPTX generation, produce or confirm a slide plan/Slide Spec first, then build the PPTX from that plan.

When the target remains genuinely ambiguous, ask one routing question: research/evidence, outline, editable PPTX, or review. Do not ask when the requested artifact or action already makes the route clear.

## Cross-Skill Handoff

- Research Pack + passing validation is the only evidence handoff into outline or deck. Outline writes draft Slide Spec `evidence_refs` with Research Pack `F`/`D`/`Q` ids; `sp-deck` compiles those into E ids. C-only work skips research and must not invent an empty pack.
- Outline-only work never creates or claims to create a PPTX.
- A file-generation request goes directly to `sp-deck`; planning happens inside that workflow.
- “看看问题” means review only.
- “直接改好” means review diagnosis followed by PPTX editing in the same task.
- Existing source decks are evidence and must not be overwritten.

## Runtime and Output Boundary

- Plugin resources and scripts are addressed through `${CLAUDE_PLUGIN_ROOT}`.
- User deliverables belong under `${CLAUDE_PROJECT_DIR}/outputs`; when that variable is unavailable, use the active project directory.
- Never write generated decks, notes, previews, or reports into the installed plugin or Claude plugin cache.

## Readability and Content Density

Follow `model-led-design.md`. Choose typography, density, colors, imagery and layout from the content, audience, user references and actual rendered pages. Preserve useful evidence and supporting detail. Respect explicitly confirmed user constraints and frozen controls in existing tasks.

## Layered Generation

Read the material and preserve the explanations, examples and evidence needed by the audience. Plan pages and notes from that content; do not turn substantial material into keywords or transfer necessary explanation exclusively into notes. See `content-workflow.md`.

Rich visible content and concise speaking notes are compatible. Plan selective oral emphasis without deleting the visible supporting detail; the content workflow owns this separation. Allowed designed placeholders follow `image-sourcing.md`, not a generic ban on every placeholder.

## Audience-facing Content — Required

PPT 正文与面向听众的讲稿直接呈现调研发现、分析结果、需求结论、方案、设计、成果和下一步行动。使用完整、连贯、自然的正式表达，让每段文字都服务于展示内容。

不要将制作说明、报告定位、任务对应关系、自我解释、自动检查范围或免责式元说明写进展示正文。例如“此内容仅能用于……，不能作为……的证据”“本页只是……，不能证明……”“未实测，因此仅供参考”不应成为页面结论。制作过程、验证范围、交付限制与排障说明放在交付对话或独立质量报告中。

保留实质性的研究条件、观测结果、业务约束、适用范围与尚待解决的问题，用具体条件和发现表达，例如“本轮在固定设备条件下记录延迟”“样本覆盖三个班级，下一轮补充跨年级观察”。不把未验证结果写成既定事实。合成样例标注简洁的数据来源“示例数据”，真实来源照常引用；不堆叠免责声明，也不伪装成真实研究。用户明确要求引用原文或展示限制条款时保留其意图。

### 直接表达与防御性说明

默认将“不是……而是……”“这并非……”“不只是……更是……”“本页旨在……”“需要说明的是……”等自我定位、预先辩护或空泛拔高改写为具体主张。检查标题、正文、图注、收束句和备注；不能只清理正文段落。不要用“可追溯、可复用、可推广”等抽象形容词在多页反复充当结论，说明具体对象、做法和有依据的变化。

| 原表达 | 直接表达示例 |
| --- | --- |
| 这不是简单的资料汇总，而是一套成长支持体系 | 汇集实验室方向、竞赛日历和项目入口，为同学提供成长路径指引 |
| 本页并非证明实际成效，仅用于说明方案 | 在正文展示方案本身；验证范围放交付报告 |
| 学生会不只是活动组织者，更是舞台搭建者 | 学生会征集同学提案、协调资源并支持班级共同策划活动 |
| 从信息堆积走向系统赋能 | 按方向、时间和参与条件整理机会信息，给出对应入口 |

上述示例说明表达方法，不能成为自动补充事实的句库。真实比较、概念辨析、研究反证或用户要求的原文引用仍可使用必要的否定句；保留有信息价值的条件和限制。判断句子的用途和证据，不按关键词机械删除。共享规范应独立包含这些要求，不能假设插件运行时能访问个人全局记忆。

生成正文默认直接陈述对象、行为、依据、结果及其关系；不使用“不是……而是……”“并非……”“由此可见”组织通用转折，不添加“xx仅作为xx参考，不是真实依据”“本页不能证明……”等防御性说明。标题、正文、图注和备注均执行；用户提供的草稿含有这些句式时也应在保留含义后改写，明确要求逐字保留的引文除外。示例数字保留简短“示例数据”，占位保留简短“素材待替换/示意图”和用户要求的生图提示词；验证限制留在交付报告，不在每页反复自我解释。

## Anti-AI Wording

Avoid:
- "In today's rapidly developing society..."
- "This topic is of great significance."
- "We should attach great importance to..."
- "It can be seen that..."
- vague phrases such as "various aspects", "many factors", and "very important" without specifics

Prefer:
- concrete class/project context
- direct claims
- examples from student life, experiments, surveys, cases, or source material
- conclusions supported by the actual material, with relevant research conditions when needed

## AI Writing Pattern Risk

Flag or rewrite text that has:
- repeated sentence structures across slides
- overly smooth transitions without concrete evidence
- broad conclusions without student-specific detail
- generic motivational summaries
- inflated claims such as "completely solves" or "comprehensively improves"

Reduce risk by adding:
- course context
- group process details
- actual observation, survey, experiment, or case details
- relevant research conditions or uncertainty when supported, without adding generic disclaimers
- specific source or data references

## English Presentation Standard

- Use B1-B2 level English for general undergraduate classroom presentations by default. Raise or lower the level when the course, audience, discipline, or speaker ability clearly requires it; do not simplify necessary technical terminology.
- Avoid complex long sentences and passive-heavy academic writing.
- Speaker notes should use natural connectors such as "First", "This example shows", "So the main point is", and "Now I will hand over to".
- Add pronunciation or glossary support for difficult keywords when useful.

## Group Presentation Standard

- Give each member meaningful content.
- Balance speaking time and difficulty.
- Include explicit handoff lines.
- Keep terminology consistent across members.
- Avoid assigning only opening or closing filler to one member.

## Chinese Presentation Norms

- Open with a concrete scene, question, or data point instead of only "Today I will introduce...".
- End with a clear closing line such as "以上是我的分享，请老师批评指正".
- For Q&A, a brief "感谢老师的提问" may introduce a direct answer with supporting facts. Acknowledge a concrete shortcoming only when it exists; do not automatically preface answers with self-criticism or defensive qualifications.
