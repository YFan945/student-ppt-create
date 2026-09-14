# Evidence And Citation Contract

## Evidence Ledger

Every factual chart, statistic, quotation, experiment result, survey finding, or case claim should map to an `evidence_ledger` entry.

Each entry records a stable `id`, short title, source type, primary locator, confidence, slides that use it, and optional limitation. Research-backed entries additionally preserve:

- `source_ids`: **all** Research Pack sources supporting the evidence;
- `primary_source_id`: the strongest source used for the short on-slide citation;
- full source metadata remains in `evidence-map.json.source_index` for bibliography/audit.

Never invent missing numbers, citations, feedback, experiments, or survey results. If evidence is unavailable, mark the claim as a proposal, assumption, illustrative example, or evidence gap.

## Claim / Data / Quote → Evidence → Source

The canonical invariant remains **Claim → Evidence → Source**; the research compiler makes the claim/data/quote-to-evidence hop mechanical rather than model-authored.

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
3. Tier D sources are opinion-only; they cannot become factual support.
4. Blocked/paywalled/missing retrieval remains in `unresolved`; affected slide wording must be downgraded rather than silently treated as verified.
5. `E<n>` ids are **compiler-owned**, never model-authored:

   ```text
   findings sorted by id
   → data_points sorted by id
   → quotes sorted by id
   → E01, E02, ...
   ```

6. The compiler can write a non-destructive **compiled Slide Spec**. Draft `evidence_refs` may use F/D/Q ids; the compiler rewrites them to E ids, replaces the Research Evidence Ledger, and recomputes `used_on_slides` mechanically.
7. `validate_research_pack.py` binds its report to `research_pack_sha256`; `evidence-map.json` binds the pack, validation report and compiled Slide Spec hashes. `slide_spec_guard.py freeze` verifies the whole provenance chain before accepting a research-backed plan.

## Delegated retrieval

All external retrieval is executed by the isolated research subagent. The main flow never searches directly and never asks for raw pages/search summaries back.

The successful handoff is exactly the fixed `RESEARCH_DONE` envelope emitted by `presentation-researcher`; content travels through files, not prose:

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
   ↓ slide_spec_guard.py freeze
Frozen plan + bound research provenance
```

Do not hand-copy the generated ledger into the spec. If the plan changes after freeze, rebuild/revalidate the affected research chain and use `revise --reason`; a research-backed revision may not silently drop its research artifacts.

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

`pptx_quality_gate_v071.py` performs deterministic closure checks on ledger usage and final references.

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