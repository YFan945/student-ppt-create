# Design benchmarks

`cases.json` freezes six six-page Chinese scenarios: defense, illustrated paper,
data coursework, student proposal, image-heavy and no-images. All achievements
and experiment data are explicitly synthetic. They exercise exact numbers,
units, mixed text, semantic compression and protected image information.

From the repository root:

```powershell
python plugins/student-presentation-suite/scripts/design_benchmark.py --output-dir E:/student-ppt-create-validation/v0.29.0 --mode auto --render
python plugins/student-presentation-suite/scripts/design_benchmark.py --output-dir E:/student-ppt-create-validation/v0.29.0 --mode guided --case chinese-defense --render
python plugins/student-presentation-suite/scripts/design_benchmark.py --output-dir E:/student-ppt-create-validation/v0.29.0 --live-claude
python plugins/student-presentation-suite/scripts/design_benchmark.py --output-dir E:/student-ppt-create-validation/v0.29.0-text --typography-stress --render
```

Outputs must be outside the marketplace checkout. The deterministic harness is
a reproducible runtime/typography benchmark, not evidence of model design skill.
The opt-in live harness runs the actual installed Claude configuration on
`chinese-defense` and `illustrated-paper`, once each for guided and auto. It uses
the same frozen facts/assets, quality tier and six-page constraint, permits at
most one repair per path, and records raw responses, monetary cost, time,
pipeline state, semantic coverage and geometry findings. Each path is bounded
with CLI budget flags of USD 1 intake + USD 6 production; unknown provider
pricing may prevent monetary enforcement or reporting. Actual model ids,
transcript usage and reported USD are recorded separately, with unavailable
costs left unknown. Resume responses contain cumulative session USD/token
values: monetary aggregation uses each session's maximum reported estimate,
not the sum of its responses. Provider billing remains unavailable. Invocation
authorizes those calls. It never runs during
the normal test/release suite.

After an infrastructure or CLI budget interruption, `--live-claude --resume-live
--continue-stages` continues the same frozen manifests. It does not reset repair
counts or start a replacement trial. The local harness executes deterministic
transitions; fresh Claude sessions perform only the dispatched Agent work, with
USD 4 per builder boundary and USD 2 per critic boundary, at most eight boundaries
per invocation. All attempts and interruption overhead remain in the results;
unknown provider prices stay unknown. Do not treat interrupted calls as free or
use continuation to exceed the page repair cap.

Evaluate the current rendered pages with an independent critic. Compare
coverage (all required ids and exact items), typography (lost/duplicated text,
unit breaks, punctuation, overflow, orphaned endings, rich-text emphasis),
protected asset regions, composition (focal point, structure, whitespace,
rhythm) and cost. Report measured differences and failures; mode names alone
are not evidence of improvement. Saved facts, prompts and output hashes make
the comparison replayable; actual Claude output can vary.

[RESULTS.md](RESULTS.md) records the observed backend, outcomes, costs and
limitations of the bounded 2026-10-11 comparison. Separate runtime replays
verify engine fixes without replacing failed live trials or refunding repairs.
