# Evidence And Citation Contract

## Evidence Ledger

Every factual chart, statistic, quotation, experiment result, survey finding, or
case claim should map to an `evidence_ledger` entry.

Each entry records:

- stable `id`;
- title or short description;
- source type;
- file path, URL, DOI, or bibliographic locator;
- author/organization and date when known;
- confidence: `high`, `medium`, `low`, or `unverified`;
- slides that use it;
- an optional limitation.

Never invent missing numbers, citations, user feedback, experiments, or survey
results. If evidence is unavailable, mark the claim as a proposal, assumption,
illustrative example, or evidence gap.

## Evidence closure

v0.7.1 要求引用形成完整闭环，而不是只在 Slide Spec 中“有 evidence id”就算完成：

```text
Slide evidence_refs
  ↕
Evidence Ledger used_on_slides
  ↓
页面短引用 / source line
  ↓
最终 References / bibliography area
```

规则：

1. 每个 `slide.evidence_refs` 必须存在于 `evidence_ledger`；
2. `evidence_ledger[*].used_on_slides` 必须与实际引用该 id 的 Slide Spec 页面完全一致；
3. `citation_style != none` 时，每个真正使用过的来源都必须能在最终 reference area 找到完整或足够明确的书目信息；
4. 页面 footer/source line 不能替代最终 references。像案例报道、技术报告、论文都不能只在中间页面短标注后从最终 reference list 消失；
5. Evidence Ledger 中完全未被任何页面使用的条目至少标记为 Minor，避免“参考文献堆积但正文没用”；
6. 引用闭环失败时优先补 references/引用呈现，不要删除 `evidence_refs` 来让检查通过。

默认 `pptx_quality_gate_v071.py` 会对 Evidence Ledger 使用关系和最终 reference area 做确定性 closure 检查。

## Gap Detection

Flag:

- numbers without an evidence reference;
- causal language supported only by correlation or anecdote;
- experiment results without baseline, sample, metric, or comparison;
- user feedback without participant count or collection method;
- current facts without date/scope;
- quotations without author or source;
- citations listed but not used on any slide;
- evidence used on a slide but absent from the final reference area;
- `used_on_slides` and slide-level `evidence_refs` disagreeing.

## Citation Styles

**Default: `classroom`（课堂引用）**。intake 不再询问引用风格，默认即课堂引用；
不要为了"展示引用风格"而在页面或讲稿中刻意强调格式（例如反复标注"课堂引用"、
或把引用风格写进开场白）。按上面各风格的自然呈现即可：幻灯片页脚/来源行简短标注，
完整出处放在讲稿或参考文献页。

- `classroom`: short source line on slide, full details in references.
- `GB-T-7714`: unified Chinese academic reference list.
- `APA`: author-date in content and APA reference list.
- `IEEE`: numbered references in the order they appear, standard in engineering and computer-science papers.
- `MLA`: author-page citations in content and a "Works Cited" list, common in humanities and language courses.
- `none`: allowed only when the presentation contains no external factual claims
  or the user explicitly accepts an unreferenced informal showcase.

Keep one style across the deck. Put full URLs and long bibliographic details in
speaker notes or references rather than shrinking normal slide text.