# Comparative Results: interpretation and source map

The authenticated Research → Comparative Results page reads completed,
owner-scoped persisted experiment runs from `GET
/api/experiments/benchmark-results`. It displays synthetic prototype results
separately from source-linked literature records. Literature metrics are not
pooled or charted together unless metric definitions and units are actually
compatible; the current contextual-only entries are intentionally not
cross-paper benchmark points.

## Current experiment versions

New Protocol V2 runs record:

- Engine `synthetic-engine-v5`.
- Workload `synthetic-workloads-v3`.
- Attack definitions `synthetic-attacks-v3`.
- Baselines `matched-six-baselines-v2` (M0–M5).
- Metrics `comparative-metrics-v4`.
- Protocol `privacyguard-research-protocol-v2`.

The run's persisted protocol/configuration is authoritative. Historical B0–B4
rows are not rewritten; API compatibility maps old input identifiers only.
Legacy records may lack protocol/evidence required for current checks and can
be marked `UNVERIFIABLE`.

## Six baselines

| ID | Definition |
|---|---|
| M0 | Raw synthetic aggregate; no privacy protection; reference only |
| M1 | Fixed epsilon; uncapped composition |
| M2 | Fixed epsilon; per-trial shared nominal budget cap |
| M3 | Fixed epsilon scaled by synthetic role factors and capped shared budget |
| M4 | Fixed epsilon, shared cap and exact cache; no adaptive history allocation |
| M5 | History-aware adaptive policy, shared cap and exact cache |

All selected baselines share data, workload, target and matched trial seeds.
The cache and cap can be dormant under some workloads, in which case baselines
may correctly produce similar results. M0 must not be described as a
privacy-preserving competitor.

## Metrics and statistical interpretation

See [`RESEARCH_METHODOLOGY.md`](RESEARCH_METHODOLOGY.md) for attack objectives,
metric formulas, denominators, Wilson intervals, continuous intervals, paired
tests and assumptions. Nominal epsilon is uncertified. In-process experiment
timing is not SQL middleware/API latency. Null or `NOT_MEASURED` metrics are
not zero. Report the scenario, numerator/denominator, sample size, uncertainty
and quality/integrity status alongside a finding.

The within-run paired analysis checks shared persisted trial seeds and does
not silently fall back to unpaired tests. Binary metrics use exact two-sided
McNemar; continuous outcomes use paired sign-flip tests and paired bootstrap
intervals; Holm correction is applied by metric family to contrasts against
the selected reference. Fewer than 20 complete pairs are exploratory. A
statistically significant result would not, by itself, establish practical
importance, external validity or formal DP.

## Literature data

The curated data source is
[`../frontend/src/data/comparative-literature.json`](../frontend/src/data/comparative-literature.json).
Each entry is maintained separately from experimental runs and should be
checked against its source citation before publication. Missing source
measurements must remain “Not reported”; incomparable values must not be
ranked against prototype results.

## Reproduction and limitations

Use [`EXPERIMENT_REPRODUCTION.md`](EXPERIMENT_REPRODUCTION.md) to recreate
software setup and a controlled run. Use
[`RESEARCH_LIMITATIONS.md`](RESEARCH_LIMITATIONS.md) for the claims the current
evidence does not support. The locked campaign runner is opt-in and was not
executed as part of the documentation audit.
