# Review Output Format

Use this structure by default. Omit sections that do not apply. Keep the review direct and actionable.

```markdown
## Overall Verdict

## What Works Well

## Critical Issues

## Slide-by-Slide Suggestions

## Speaking And Notes

## Evidence And Citations

## Rehearsal And Timing

## Group Handoffs

## Quick Fix Priority

## Edit Plan

## Change Summary Handoff

## Before/After Diff
```

Only when scoring is requested, add the requested score dimensions or per-slide scores; concrete findings are the default.

When requested, add a Training Card for each slide:

```markdown
### Slide N Training Card
- Speaking goal:
- Keywords:
- Planned seconds:
- Likely question:
- Answer points:
- Avoid overstating:
```

For each issue, include exactly four fields, mapping 1:1 to the `review_findings` items in
`../../references/slide-spec.schema.json` (`additionalProperties: false` — do not add extra keys):
- severity (Critical / Major / Minor)
- target — slide/page number when known (e.g. `Slide 4`)
- problem — the issue and why it matters
- fix — concrete fix

Example:

```markdown
- severity: Major
  target: Slide 4
  problem: The title "Analysis" does not tell the audience the conclusion; the header must carry the takeaway.
  fix: Rename it to "Convenience is the main reason students choose short videos for news".
```

Use `Edit Plan` only when the user asks to optimize, modify, regenerate, or directly improve a deck. Include:
- what to keep
- what to rewrite
- what to redesign
- whether to preserve the original structure or rebuild a cleaner copy
- whether file editing is requested or only advice is requested

Use `Change Summary Handoff` when file editing is requested. It must be concise enough to pass into `sp-deck` and should include the expected improved PPTX filename plus `outputs/<topic>-change-summary.md`.
