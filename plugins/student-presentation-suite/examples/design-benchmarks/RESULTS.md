# Observed comparison — 2026-10-11 to 2026-10-12

These are bounded runs of the installed Claude Code CLI using the frozen
`chinese-defense` and `illustrated-paper` six-page cases. The observed backend
was `deepseek-v4.1-flash`; the defense auto transcripts also contain `glm-5.3`.
They are not Anthropic Claude model results. Synthetic transcript markers are
not model identities. All scenario facts and experiment values are synthetic.

| Cohort | Case | Mode | Final state | Repairs used / cap | Known CLI session USD estimates |
| --- | --- | --- | --- | --- | --- |
| Original | Chinese defense | guided | incomplete | 1 / 1 | 16.923675 |
| Original | Chinese defense | auto | complete | 1 / 1 | 11.038417 |
| Original | Illustrated paper | guided | incomplete | 1 / 1 | 12.668162 |
| Original | Illustrated paper | auto | complete | 1 / 1 | 7.643953 |
| Authorized additional | Chinese defense | guided | incomplete | 1 / 1 | 10.029632 |
| Authorized additional | Illustrated paper | guided | complete | 1 / 1 | 11.076040 |

Resume responses contain cumulative session USD and token values. The table
sums each session's maximum reported estimate, retaining interrupted and
continued attempts without counting a resumed session twice. This corrects
the earlier per-response summation. Some interrupted calls have unknown costs and the
provider's actual billed prices are unavailable. These values are partial CLI
estimates, not invoices or a reliable comparison of mode efficiency.

The two complete paths have independent reviews covering all six required
semantic ids. Defense auto repaired unsupported bar heights that implied an
unstated quantitative ratio. Paper auto received composition advice, including
a low subjective score; this remained advice under the new contract. Delivery
gate defects discovered during these runs were fixed with regression coverage.
Their consumed repair counts were retained.

Defense guided stopped on an invalid sequence payload in the current source;
its older rendered deck and review do not certify that source. Paper guided
rendered all six pages and covered all six semantic ids, but the independent
critic found an orphaned cover ending and split Chinese retrieval terms. Both
paths exhausted their one-repair cap and retain `incomplete` status.

The runtime fixes now balance guided last lines, preserve Chinese word
segments and numeric count units across rich runs, and display protected
figure assets at their measured aspect ratio. Separate replays of the saved
paper guided source passed text readback and rendered inspection of those
fixes. These replays did not edit the original trial or replace its failure.

The user authorized two additional guided trials in separate directories,
each still capped at one repair. Additional paper guided completed with all six
semantic ids covered. Additional defense guided repaired page 4's fit failure,
then stopped on a new page 6 fit failure: 60pt text required 3.933in in a 2.87in
region. Its cap was exhausted and the pipeline correctly retained `incomplete`.
No second repair or new replacement beyond these two authorized trials ran.

The additional runs exposed a standalone preflight import-path issue and a
self-check false positive on measured CJK/numeric spans; both now have regression
coverage. Same-row adjacent logical spans are joined for inspection without
loosening numeric token boundaries. Stage continuation also recognizes YAML
Production Summaries and does not repeat intake. Recovery invocation history
remains in the evidence.

The interrupted invocations,
changing runtime during debugging, mixed backend and small sample prevent a
causal claim that auto improves design quality. Generated decks, PNGs, raw
responses, transcripts and hash-bound review evidence remain outside Git.
See [README.md](README.md) for reproduction and evaluation rules.
