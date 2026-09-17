# Shared Student Presentation Standards

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
budget, and the Research Pack contract), and `cost-discipline.md` owns how the
work is carried out: batched tool calls, in-place edits, write-once artifacts,
stage summaries, delegated search, and single-run gating.

## Intent Routing

Before routing to any skill in this suite, require both a clear student-owned academic context and an explicit PPT-related intent. Strong context includes an identified student, university assignment, classroom report, thesis/course defense, teacher rubric, or student competition. Do not treat a single ambiguous word such as "course", "class", "competition", or "defense" as sufficient without supporting academic cues. PPT-related intent must be one of: requesting a PPT/slide outline; requesting PPT/PPTX creation or improvement; requesting review of an existing PPT artifact; or requesting external facts, current data, statistics, citations, or a Research Pack that will support such a deck (including user-material-only scope D). Do not use this suite for generic presentation work, standalone scripts/Q&A, attached decks without a review request, or non-student presentations.

Choose the skill by the user's requested outcome, not only by the input type:
- Use `sp-research` when an eligible student-context request needs external facts, current data, statistics, citations, or a Research Pack, including scope-D compilation of the user's own materials. It never designs slides or creates PPTX.
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

## Classroom Readability

- Chinese normal body text should be 22pt or larger.
- English normal body text should be 20pt or larger.
- **Bilingual slides** (中英混排): use 22pt as the minimum for mixed content to ensure Chinese readability; English at 22pt remains comfortably readable. When Chinese and English appear in separate text blocks on the same slide, Chinese blocks follow the 22pt rule and English blocks follow the 20pt rule.
- Primary slide titles should normally be 24pt or larger. Subtitles, card headers, chart titles, panel labels, legends, diagram labels, and other secondary text may be smaller when the layout requires it, but must remain projection-readable.
- Smaller text is allowed for secondary labels, captions, citations, footnotes, chart labels, diagram annotations, or minor explanations.
- Keep slide text inside boxes with comfortable padding.
- Prefer high contrast and simple classroom projection-friendly layouts.

## Slide Density

- One slide should carry one core message.
- Normal slides should use no more than 4 bullets.
- Normal slide text should stay compact: roughly up to 80 Chinese characters or 40 English words, excluding citations, captions, and chart labels.
- Keep slide text concise; move explanation to speaker notes.
- Use one chart/table per data slide and add one conclusion sentence.
- Split slides instead of shrinking text.
- When the confirmed Presentation Brief provides stricter per-slide limits,
  those limits override these defaults.

## Layered Generation

Generate in this order: directory, slide claim/supporting points, concise PPT
copy, speaker version, then Slide Spec/PPTX. Use `content-workflow.md` for
structure modes, story checks, and compression rules. Do not present speaker
notes as slide body text.

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
- modest conclusions that admit limits

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
- limits and uncertainty
- specific source or data references

## English Presentation Standard

- Use B1-B2 level English for general undergraduate classroom presentations by default. Raise or lower the level when the course, audience, discipline, or speaker ability clearly requires it; do not simplify necessary technical terminology.
- Keep each slide to 2-4 short sentences or phrase groups.
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
- For Q&A, use polite framing such as "感谢老师的提问" and "这个问题确实是我们考虑不够充分的地方".
