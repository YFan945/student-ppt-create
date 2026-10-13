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
The opt-in live harness uses the actual configured Claude backend with frozen facts/assets. It records responses, observed model IDs, time, usage, pipeline state and geometry. It has no monetary, token, request-count or repair-round budget gate. CLI monetary estimates are observational; unavailable provider billing remains unknown. Same-session cumulative cost values are aggregated by maximum, not summed. Invocation authorizes model calls; this harness never runs in the normal test/release suite.

After an infrastructure interruption, `--live-claude --resume-live --continue-stages` continues the existing manifests and pages. Preserve earlier attempts in the results instead of starting a replacement trial.

Inspect all complete current renders and compare required facts, typography, image regions, composition and page rhythm. The main session checks meaning and visuals; no independent critic is provided. Report actual observations and failures, since mode names do not establish improvement.

[RESULTS.md](RESULTS.md) preserves the historical 2026-10-11 comparison, including the limits and failures used at that time; it does not define current runtime policy.
