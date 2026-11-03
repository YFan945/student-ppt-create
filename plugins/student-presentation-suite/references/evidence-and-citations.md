# Evidence And Citation Contract

## Evidence Ledger

Every factual chart, statistic, quotation, experiment result, survey finding, or case claim should map to an `evidence_ledger` entry.

Each entry records a stable `id`, short title, source type, primary locator, confidence, slides that use it, and optional limitation. Research-backed entries additionally preserve:

- `source_ids`: **all** Research Pack sources supporting the evidence;
- `primary_source_id`: the strongest source used for the short on-slide citation;
- full source metadata remains in `evidence-map.json.source_index` for bibliography/audit.

Never invent missing numbers, citations, feedback, experiments, or survey results. If evidence is unavailable, mark the claim as a proposal, assumption, illustrative example, or evidence gap.

## Claim / Data / Quote → Evidence → Source

The canonical invariant remains **Claim → Evidence → Source**; the research compiler makes the claim/data/quote-to-evidence hop mechanical rather than model-authored. The retrieval, source-tiering, conflict, and A/B/C/D rules are owned by `research-workflow.md`; this file owns how validated research becomes slide evidence and citations.

External knowledge enters through `sp-research` and the Research Pack. The canonical chain is:

```text
Draft Slide Spec evidence_refs: F03 / D07 / Q02
            ↓  research_pack_to_evidence.py
Compiled Slide Spec evidence_refs: E02 / E09 / E11
            ↓
Evidence Ledger E<n>
   ├─ source_ids: [S01, S04, ...]     # all supporting sources
   └─ primary_source_id: S04          # strongest short-citation source
            ↓
Research Pack sources S<n>
            ↓
page short citation → final bibliography
```

Rules:

1. Research Pack is the sole entry point for external facts. Numbers, factual claims and direct quotations must trace to a `finding`, `data_point`, or `quote`, then to source(s).
2. `confidence: low` or `conflict: true` must survive into the ledger limitation and into qualified/range wording on the slide.
3. Source tiers and confidence are metadata, not source-count quotas or reasons to keep searching. Trace adopted facts to a readable source and its locator. Independent corroboration is required only for explicit `cross_check`, judged by original reports/data sets rather than domain count; see `research-workflow.md`.
4. Opinion sources (community / personal-blog / vendor-blog) do not block a claim (owner ruling 2026-09-30): a number resting solely on them passes with a minor advisory (`opinion_only_support`), and the slide must attribute it as a community/vendor view rather than an established fact.
5. Blocked/paywalled/missing retrieval remains in `unresolved`; affected slide wording must be downgraded rather than silently treated as verified.
6. `E<n>` ids are **compiler-owned**, never model-authored:

   ```text
   findings sorted by id
   → data_points sorted by id
   → quotes sorted by id
   → E01, E02, ...
   ```

7. The compiler can write a non-destructive **compiled Slide Spec**. Draft `evidence_refs` may use F/D/Q ids; the compiler rewrites them to E ids, replaces the Research Evidence Ledger, and recomputes `used_on_slides` mechanically.
8. Handoff and compilation validate current content and refresh older reports automatically. Hashes and execution receipts are observational in ordinary research; only explicit text-bound audits require the historical byte chain. Content references and the final Slide Spec still need to agree.

## Delegated retrieval

All external retrieval is executed by the isolated research subagent. The main flow delegates retrieval; it may inspect a bounded supporting passage to resolve a concrete doubt, without repeating the research or importing whole pages.

The default successful handoff is the fixed `RESEARCH_DONE` envelope emitted by `presentation-researcher`; content travels through files, not prose:

```text
research-pack.json
research-pack-validation.json
RESEARCH_DONE envelope with paths/counts/status only
```

Raw retrieval stays at `outputs/.pptx-work/<work-id>/research/<topic>.json` and is audit-only.

## Evidence compiler contract

For research-backed decks the canonical order is:

```text
Research Pack
   ↓ validate_research_pack.py
research-pack-validation.json
   ↓
Draft Slide Spec with F/D/Q evidence_refs
   ↓ research_pack_to_evidence.py
Compiled Slide Spec + evidence-map.json
   ↓ validate_slide_spec.py
Slide Spec validation report
   ↓ current production inputs
Editable plan + adopted source provenance
```

Do not hand-copy the generated ledger. Planning and previews can proceed while research is pending. Before complete delivery, the compiler refreshes adopted evidence and requested core gaps; unused candidate evidence does not block adopted facts. Revise the current plan in place; no freeze/revise command or receipt chain is required.

## Evidence closure

Citation closure is required, not merely the presence of an id:

```text
Slide evidence_refs
  ↕
Evidence Ledger used_on_slides
  ↓
page short citation / source line
  ↓
final References / bibliography area
```

Rules:

1. every `slide.evidence_refs` exists in `evidence_ledger`;
2. `used_on_slides` exactly matches the actual Slide Spec references;
3. when `citation_style != none`, every used source remains identifiable in the final reference area;
4. page footer/source lines do not replace the final bibliography;
5. unused ledger entries are at least Minor findings;
6. fix missing reference presentation instead of deleting evidence refs to game the gate.

**Match against the sources, not against the evidence claims.** `evidence_ledger.title` is a
claim, a value or a quote — `research_pack_to_evidence.py` builds it from `finding.claim` /
`data_point.meaning` / quote text — so it is text a bibliography never carries. The bibliography
renders `source_ledger`, the same records the compiler writes into the spec, and the closure check
resolves each used entry's `source_ids` to those records. A cited id the ledger does not contain is
`unresolved_source_ref`; a resolvable source missing from the reference area is
`missing_final_reference`. 2026-09-18 live: matching claim text against the band failed for 16 of
42 used entries no matter what the pages said, which pinned QA above zero and made `complete`
unreachable by construction — the band already listed all 25 source titles verbatim.

Current validation follows `validation-policy.md`; legacy quality modules are explicit diagnostics, not an additional production gate.

## Gap Detection

Flag:

- numbers without an evidence reference;
- causal language supported only by correlation or anecdote;
- experiment results without baseline, sample, metric, or comparison;
- user feedback without participant count or collection method;
- current facts without date/scope;
- quotations without author/source;
- citations listed but unused;
- used evidence absent from the final reference area;
- `used_on_slides` and slide-level refs disagreeing.

## Citation Styles

Default is `classroom`: concise source line on slide, full details in references/speaker notes. Other supported styles are `GB-T-7714`, `APA`, `IEEE`, `MLA`, and `none` (only when there are no external factual claims or the user explicitly accepts an informal unreferenced showcase).

Keep one style across the deck. Do not shrink ordinary slide text to fit long URLs or bibliographic details.
