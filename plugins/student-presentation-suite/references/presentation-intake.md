# Presentation Intake

This file owns clarification, the Production Summary and intake state. For new 2.1 tasks, model-led-design.md owns visual freedom; actual user constraints remain binding. Reuse supplied materials and confirmed choices.

## Intake modes

- PPTX creation/editing: inspect material, resolve consequential gaps, show one complete Production Summary and obtain approval before production.
- Outline-only: clarify only missing decisions affecting content, evidence or speaking requirements; state reasonable assumptions for optional preferences.
- Review-only: inspect the supplied artifact without modifying it; ask only for missing context that materially changes the diagnosis.
- Beginner explains recommendations; expert keeps them short. Neither mode adds mandatory preference questionnaires.

## Resolve the brief

Separate current instructions from pasted historical tool logs. Read supplied files first: identify missing facts, conflicting versions, usable images, template requirements and output expectations. Historical environment checks are not current evidence.

Ask only about unresolved decisions that change correctness, scope, permissions or the requested result. Group related choices in a small AskUserQuestion batch; do not ask one question for every schema field. Optional preferences may be reasonable stated assumptions in the summary. Do not re-ask authorized choices. If the user says “你决定/按推荐来”, complete remaining preferences yourself and present the full summary for approval.

The summary must cover these controls, using concise grouped prose or rows:

| Controls | Recommendation when absent |
| --- | --- |
| Topic, course/context, presentation type, scenario, rubric/required sections | Restate the actual topic and course; undergraduate coursework only when consistent with the request; no invented rubric |
| Audience, audience depth, language | Teacher/classmates, standard, user's language |
| Duration, slide count | Propose a material-appropriate scope; 5 minutes and 7–9 pages are suggestions, never automatic caps |
| Individual/group, members and ownership | Individual unless members are named |
| Source material, research scope, sources/citations | User material and authorized evidence; Classroom citation style unless otherwise needed |
| Source deck, edit intent, preserve | New deck → create; editable source → edit_ooxml; explicit rebuild or non-PPTX → rebuild_from_source; preserve the original |
| Template, branding/logo, visual direction | Reuse supplied requirements; propose one content-fit direction when delegated |
| Image strategy, permissions, unavailable assets/placeholders | hybrid-adaptive: inspect local assets and actual available tools; retain explicit prohibitions; ask about designed placeholders only when not already authorized |
| Content and speaking plan | Substantive visible explanation with selective speaking notes; no default word/Chinese-character cap |
| Structure, interaction and quality | Structure from material; beginner guidance; fast unless requested quality calls for standard/rigorous |
| Deliverables, output_dir/output_prefix, export/versioning | PPTX only by default; outputs/<work-id>; preserve source/version for edits; add change-summary for edits |

Map these controls to the existing Slide Spec meta fields; use top-level source_deck, edit_intent, preserve, review_findings and change_summary_required for edits. Only write max_words_per_slide/max_chinese_chars_per_slide when expressly requested. Quality actions are owned by presentation-brief.md, not additional production stages.

## Visual direction and image capability

A style name provides palette/font-family guidance, not page composition. Reuse reference decks and user wording. If a visual choice is genuinely unresolved, present a few relevant directions with their concrete differences. The optional style menu groups 学术与专业类、商务与科技类、创意与人文类; do not force category and subtype rounds. Exact names come from design-tokens.json. Use Other with visual_style_custom when appropriate; describe actual style_character/palette, not unused background or SVG recipes.

Before promising imagery, inspect supplied files and available tool declarations. Missing image-sources.json means acquisition is undeclared, not user refusal. Follow image-sourcing.md to record an available authorized provider; do not make paid/network test calls merely to fill an intake field. An unavailable tool cannot be offered as ready. No-web does not by itself forbid supplied images or already authorized concept generation. Rich native diagrams remain an option, not an automatic substitute for every missing photo.

Do not run environment, generation, rendering or delivery commands in intake_pending. One environment check (`check_claude_pptx_env.py`) is allowed before `init`, so the summary can state real capabilities (rendering, imagery); once a work-id exists in intake_pending, wait for approval. Existing reference images can be inspected. If the user wants a generated style comparison, first approve a complete summary for that limited preview task; run it under its own work-id, then confirm the full deck summary. Alternatively inspect representative pages during the approved deck's normal authoring. There is no implicit preview exemption from intake. Style previews remain synthetic examples and do not establish final content or require an extra style-approval stage for ordinary tasks.

## Production Summary

Show the full summary including assumptions, existing-deck preservation, planned output directory, exact deliverables, imagery permissions and allowed placeholders. Use AskUserQuestion to obtain an affirmative reply (confirm / adjust). Only approval of this summary moves intake_pending to intake_confirmed. Do not re-confirm a summary already approved in the current task. A prior authorization applies to its stated scope; changes to facts, deliverables or permissions must remain within it.

Example: “中文课程汇报，老师与同学，5分钟约8页，个人；使用已给材料，不外查；沿用蓝灰参考的层级并按内容变化构图；优先本地图片和可编辑图解，允许已确认的素材占位；正文保留支撑，备注讲重点；交付PPTX到outputs/course-report。” Ask only about consequential missing choices before this final approval.

## Deliverables vs. pipeline evidence

Deliverables are precisely what the user selected. Internal full-page renders, contact sheet and technical reports are pipeline evidence; do not promise them as exports unless selected. Embedded include_speaker_notes is separate from an exported speaker-notes.md. Preview exports every slide; contact-sheet is the overview. Additional PDF, outline, script, quality-report or rehearsal material needs the corresponding scope. Editing requires change-summary.md.

## Planning ownership

The approved summary captures user authorization. Slide Spec meta stores production controls and slides store content/visual intent. Keep narrative progression and brief visual conventions in the existing handoff-plan when useful; do not rewrite all controls there. A separate Presentation Brief is optional for cross-task reuse or a user-supplied brief, not a mandatory second copy for every PPTX. When supplied, validate it and carry controls consistently into Spec; do not ask for two approvals of the same plan.

## Workflow states and recovery

intake_pending → intake_confirmed → planned → producing → qa → complete

- workflow_guard.py init/confirm persists intake and the approved summary hash.
- ppt_pipeline.py plan validates approved inputs and creates page sources; its build-manifest.json owns production state and mirrors workflow-state.json.
- run builds/checks/renders and returns to qa, including after fixes. Rework is qa → producing → qa through run; there is no repair subcommand.
- complete verifies current artifacts and exports selected types after author inspection.
- A failed run preserves evidence and records its actual error. Correct that cause and run again under the same approved work-id. Do not restart intake for a missing dependency or a routine design repair.
- status reads current checks, publication health and historical manifests without rebuilding. Old production manifests are read-only; use a new approved edit task preserving the original to continue them.
- blocked/incomplete describe real inability to proceed or missing required output; never claim completion while required work is missing. Changes outside approved scope need revised authorization, not an automatic reset for every warning.

Commands and rendering/inspection requirements live in skills/sp-deck/references/main-session-production.md. Do not manually transition production states or move frozen inputs/deliverables after complete.

## Work isolation

Use one work-id consistently with init/confirm and outputs/.pptx-work/<work-id>. A manifest binds its state path and approved summary. Never reset another deck's work; do not trust legacy global state as current authorization. User artifacts stay in the active project's outputs, outside the installed plugin and marketplace repository.
