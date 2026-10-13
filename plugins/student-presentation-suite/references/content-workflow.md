# Layered Content And Story Workflow

Use this workflow after the Presentation Brief is confirmed.

展示文案执行 shared-standards.md 的重要正文语言规范：直接写发现、分析、结论和行动；制作或自动验证说明留在交付对话，不冻结为页面主张。

## Generation Layers

1. Directory: section names, purpose, timing, and story order.
2. Slide points: one claim and supporting points for each slide.
3. PPT copy: concise text that obeys the confirmed density limits.
4. Speaker version: natural explanation, evidence context, transition, and timing.
5. Slide Spec: structured handoff for production, review, and local revision.

Do not collapse these layers into one long draft. A slide body is not a script.

## Structure Modes

- `problem-solution`: problem → cause → solution → implementation → proof → value.
- `research`: question → method → results → interpretation → limits.
- `timeline`: starting point → stages → turning points → current state → next step.
- `comparison`: criteria → option A/B evidence → tradeoff → recommendation.
- `case-study`: context → challenge → action → result → lesson.
- `product`: user pain → proposition → workflow → implementation → validation → value.

## Story Checks

Before handoff, check:

- duplicate claims or pages;
- a result shown before its method/evidence without a deliberate executive-summary opening;
- a conclusion that introduces new evidence;
- missing transition between different logical sections;
- background consuming more time than method, result, or insight;
- an opening without a hook;
- a closing without takeaway, limitation/next step, and Q&A cue.

## PPT And Speaker Versions

PPT copy keeps the claim, keywords, numbers, and contrast. Speaker notes explain:

- why the claim matters;
- how the evidence was obtained;
- one concrete example;
- one limitation where relevant;
- the transition to the next slide.

When compressing, remove explanation before removing evidence. When expanding,
add examples, evidence context, comparison, causal reasoning, or limitations;
do not add generic filler.

## Teaching Explanation

In `beginner` mode, explain each major structural or visual choice in one short
sentence: what audience problem it solves and what mistake it avoids. Keep this
rationale in the outline, quality report, or change summary rather than adding
it to the visible slide unless requested.

## Anti-Generic Rewrite

Flag and rewrite:

- broad importance statements without a concrete subject;
- repeated sentence patterns;
- conclusions stronger than the evidence;
- generic benefits such as “improves efficiency” without mechanism or measure;
- smooth transitions that hide a missing logical step.

Use `scripts/analyze_presentation_spec.py` for deterministic structural,
density, evidence-reference, and wording-risk checks.
