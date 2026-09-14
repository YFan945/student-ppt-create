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

## Claim → Evidence → Source

v0.9 起，外部知识经 `sp-research` 汇成 **Research Pack**，再进入 ledger。链路固定为：

```text
Slide 06
  ↓  slide.evidence_refs
Claim C06-01        ← research-pack findings / data_points
  ↓  source_ids
Source S08          ← research-pack sources（含 tier 与 url/locator）
  ↓
页面短引用 → 最终参考文献
```

规则：

1. Research Pack 是**外部事实的唯一入口**。页面上任何外部数字都必须能追到 a
   `finding` / `data_point`，再到具体 `source`；追不到的不许上屏。
2. Research Pack 的 `confidence` 决定 ledger 的 `confidence` 与页面表述方式：`low`
   或 `conflict: true` 的条目，页面必须写成区间或加限定语，不得当确定值陈述。
3. `tier` 为 D 的来源只能作为"用户观点/舆论"引用，不得作为事实依据。
4. 检索受阻（打不开、付费、不可得）必须留在 pack 的 `unresolved` 里；对应论断在页面
   上要标注为无来源或降级表述，不得静默当作已证实。
5. `E<n>` 由 `scripts/research_pack_to_evidence.py` **确定性分配**，不由模型手写：

   ```text
   findings 按 id 排序 → data_points 按 id 排序 → E01, E02, …
   research-pack.json  →  evidence-map.json（ledger + F/D/S→E 映射 + 来源索引 + 哈希）
   ```

   同一个 pack 编译两次必须得到完全相同的 ledger。该脚本同时拒绝编译未通过
   `validate_research_pack.py` 的 pack——未经验证的 pack 不是交付物，不许变成证据。
6. 规则与判定标准见 `research-workflow.md`；`scripts/validate_research_pack.py` 会强制
   第 1、2、3 条，`research_pack_to_evidence.py` 会强制第 5 条。

## Delegated retrieval

话题资料检索、事实与数据核查、案例与竞品搜索等**一切外部检索**都由子代理执行
（见 `cost-discipline.md` CD-5）；主流程不直接发起检索。完整的研究规约与产出形状见
`research-workflow.md` 与 `research-pack.schema.json`。

**只有一条交接协议**（v0.10 起）。子代理回传三项，且只有这三项：

```text
research-pack.json              结构化研究结论（唯一内容载体）
research-pack-validation.json   validate_research_pack.py 的校验结果
compact summary                 几行状态：覆盖了哪些 claim、哪些没查到
```

主流程消费的是 `research-pack.json` 这份文件，**不是**任何临时文本格式。早期文档里
"子代理返回 ≤20 行结论、主流程据此手写 ledger 条目"的做法已废止——它让模型在最后
一步重新自由发挥，而这一步正是 Research Pack 要消灭的。

随之固定两条：

- 原始检索结果落盘 `outputs/.pptx-work/<work-id>/research/<topic>.json`，**不回传**；
- `F/D/S` → `E` 的转换由 `scripts/research_pack_to_evidence.py` 确定性地完成，
  见下一节。子代理不写 ledger 条目。

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