# Student Presentation Review Checklist

Load `../../../references/shared-standards.md` for confirmed constraints, readability, anti-AI wording, AI-writing pattern risk, English, Chinese, and group standards. Load `../../../references/image-strategy.md` for image/source expectations.

## Severity

Critical:
- audience cannot understand the main point
- required defense/report sections are missing
- slides are unreadable due to text size, contrast, clipping, or overflow
- group presentation has clearly unfair or broken handoffs
- English presentation is too difficult to speak naturally

Major:
- evidence-slide titles obscure the actual finding when a supported takeaway would materially improve comprehension; direct subject titles remain appropriate for definitions, mechanisms, setup and process
- paragraph/script-like text makes the page hard to browse or obscures emphasis; rich supporting detail with clear hierarchy is not itself a defect
- evidence, data, or examples are not interpreted
- visuals are decorative or unrelated
- notes are robotic, essay-like, or missing key transitions
- timing likely does not fit the required duration

Minor:
- inconsistent spacing or visual rhythm
- small wording polish
- weak conclusion wording
- optional pronunciation/glossary support
- minor source or citation cleanup

## Structure Review

Check:
- the deck has a clear story arc
- the opening explains why the topic matters
- each section connects to the next
- every slide has one main message
- the conclusion restates the main finding or lesson
- Q&A or thank-you ending is suitable for the presentation type
- repeated claims/pages are merged or clearly differentiated
- method/evidence appears before supported conclusions unless an intentional executive-summary opening is used
- transitions explain the relationship between sections

Defense decks should include:
- background
- objective or research question
- method, design, or work process
- results or implementation
- problems and fixes when relevant
- limitations or future work
- Q&A

## Slide Content Review

Check:
- title form fits the page function: direct subject titles for explanation/setup, supported takeaways for findings, descriptive titles for cover/divider/reference pages; no mandatory second conclusion band
- body text is short enough to present
- useful evidence and supporting detail remain visible where needed
- data slides communicate the supported interpretation through title, annotations or nearby explanation without requiring a repeated conclusion sentence
- examples connect to the main argument
- public-facing text follows the required Audience-facing Content section of shared standards; production/verification caveats are reported in the delivery conversation

## Classroom Readability

Judge readability from the actual rendered pages and intended audience; enforce only confirmed user constraints.

Flag:
- text or labels unreadable at the intended viewing size
- low contrast
- text touching edges
- clipped or overflowing text
- crowded diagrams
- charts with unreadable axes or labels
- visually empty slides with only a vague sentence

## Visual Review

Check:
- images support the message
- images are clear enough for projection
- diagrams simplify the idea
- icons communicate clearly and fit the composition
- background effects do not reduce readability
- real people, places, products, historical materials, and current examples use appropriate factual sources when needed
- image source and fallback choices match `../../../references/image-strategy.md`
- allowed designed placeholders are substantive, visibly identified and replaceable; rich body content has a selective speaking path and concise notes
- cover reading focus, semantic title breaks and grouped metadata are coherent; required template dimensions, masters and repeated objects survive

## Anti-AI Wording

Use `../../../references/shared-standards.md` as the canonical anti-AI wording and AI-writing pattern risk standard. In reviews, quote only the specific deck wording that needs to change and provide a student-like replacement.

## AI Writing Pattern Risk Review

Flag:
- repeated sentence structures across multiple slides
- smooth but empty transitions
- broad conclusions without student-specific details
- claims that sound too complete or inflated
- lack of course, group, survey, experiment, or process details

Fix by adding:
- one concrete class/project detail
- one actual observation or data point
- one limitation or uncertainty
- one source note where evidence appears
- one phrase that reflects the student's own process

Do not claim to predict an AI detector result. Describe these as writing-pattern risks.

## English Presentation Review

Check:
- B1-B2 level vocabulary and grammar for general undergraduate classroom presentations by default, adjusted for course level, discipline, audience, and speaker ability
- notes use natural connectors
- long sentences are split
- difficult terms have optional pronunciation or glossary help
- speaker can say the notes aloud without sounding like an essay

## Group Presentation Review

Check:
- each member has meaningful content
- speaking time is balanced
- technical difficulty is distributed
- handoff sentences are clear
- terminology and style are consistent across members
- opening and closing are not used as filler roles

## Five-Dimension Score

When useful, rate each dimension as Excellent / Good / Needs Work / Risk:
- Logic structure: story arc, claim clarity, evidence chain
- Visual design: readability, layout, consistency, image usefulness
- Speaker notes: naturalness, timing, transitions, confidence
- Defense readiness: Q&A, limitations, source awareness, rubric fit
- Originality/student feel: concrete details, non-generic wording, personal or group process

Include one sentence explaining the score for each dimension. Do not let scoring replace concrete fixes.

For machine-readable review, use 0-100 scores for logic, evidence, readability,
speakability, and defense readiness. Run `analyze_presentation_spec.py` when a
Slide Spec is available; rendered deck evidence still overrides heuristics.

## Evidence Review

Check Evidence Ledger coverage, source date/scope, sample/metric/baseline,
confidence, limitations, and citation consistency. Numeric, causal, quotation,
survey, experiment, and case claims must not be invented or left untraceable.

## Rehearsal Review

Check total and per-slide timing, abrupt timing changes, missing transitions,
notes that are difficult to say naturally, likely teacher/judge questions, and
whether source/method/limitation/feasibility challenges can be answered.

## Positive Feedback

Include strong parts worth keeping when the deck has them; omit this section when no defensible positive evidence is available:
- clear topic angle
- strong data/example
- readable slide
- good visual explanation
- natural handoff
- honest limitation
- memorable conclusion

## Rubric-Aligned Review

If the user provides a rubric:
- organize feedback under the rubric dimensions
- estimate likely strengths and weak spots
- do not invent exact scores unless the rubric supports them
- map quick fixes to the highest-weight criteria first

## Slide Spec Vs Actual

When a Slide Spec YAML is provided with a deck:
- compare planned title, layout, content, visual purpose, timing, and owner with the actual slide
- flag lost design intent, missing visuals, changed claims, or timing drift
- treat differences as risks unless the actual slide is clearly better

## Before/After Diff Review

When two versions are provided:
- list fixed issues
- list unresolved issues
- list new issues introduced by the revision
- identify whether the newer version is clearly better, slightly better, mixed, or worse
- give the next 3 highest-priority fixes

## PPTX XML Static Check

For `.pptx` files, run `python "${CLAUDE_PLUGIN_ROOT}/skills/sp-review/scripts/pptx_static_check.py" <deck.pptx> --json` to scan static XML risks:
- font size below threshold
- high text density
- small text boxes
- paragraph-heavy text
- excessive color complexity

Use `--strict` only for automated validation where a failed scan should fail the step. Treat script output as risk evidence, not absolute proof. `font-size-not-explicit` often means the script could not resolve inherited theme or master styles, not that the deck is definitely unreadable. True overflow and projection readability still need rendered previews or manual inspection.

## Suggested Output

Use `review-output-format.md` as the single source for the four-field `review_findings`
contract, examples, edit plan, and change-summary handoff. This checklist only determines
what to inspect and how to classify the evidence.
