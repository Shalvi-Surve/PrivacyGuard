# Research methodology and metric definitions

This guide is the readable companion to the run-specific protocol object
defined in [`RESEARCH_PROTOCOL_V2.md`](RESEARCH_PROTOCOL_V2.md). The persisted
protocol for an individual run is authoritative for that run. Historical runs
without Protocol V2 must not be retroactively interpreted under these rules.

## Experimental unit and synthetic data

The experiment is a controlled synthetic simulation. A run generates one
synthetic employee dataset in memory from a dataset seed, then evaluates each
selected baseline on the same generated records and matched trial seed
schedule. Current generator identifier is `synthetic-employee-generator-v1`;
it uses Python `random.Random(seed)` and deterministic choices for department,
designation, age, salary, performance score, gender and location. It does not
read registered application datasets. Reproduction requires the same source
revision, Python random implementation/version, generator version, parameters
and seed. The protocol currently stores Python and platform versions.

Current generator parameters in source: department is uniform over Engineering,
Finance, HR, Operations, Sales, Legal, Research and Support; designation index
is `clamp(int(N(2.1, 1.05)), 0, 4)` over Associate, Specialist, Senior, Lead
and Manager; age is `clamp(int(N(39, 9)), 21, 65)`; performance is
`round(clamp(N(2.8 + 0.22 × designation_index, 0.65), 1, 5), 2)`; gender is
uniform over four labels; location is uniform over North, South, East, West
and Central. Salary is the integer-clamped value
`base[designation] + (age - 38) × 520 + (performance - 3) × 4000 + N(0, 8500)`
within 32,000–260,000. Designation bases in order are 48,000, 68,000, 92,000,
120,000 and 142,000. IDs are deterministic row ordinals scoped by synthetic
dataset ID. The random draw order is part of the generator version; changing
it requires a new version.

## Attack objectives and success criteria

| Scenario | Objective and estimator | Success condition | Scope caveat |
|---|---|---|---|
| Difference | Individual contribution: Engineering salary sum minus the same sum excluding one selected synthetic employee | Absolute estimate error ≤ configured relative tolerance × `max(abs(target), 1)`; default 5% | Contribution inference, not membership inference |
| Repeated | Full-dataset salary aggregate; arithmetic mean of answered repeated outputs | Same 5% relative criterion | Aggregate reconstruction, not individual inference; exact repeats may reuse one draw |
| Narrowing | Fixed scripted sequence of progressively narrowed COUNT queries; use final cohort count | Absolute error ≤ configured count tolerance; default 1 | Not an interactive attacker; small-group flag also requires cohort size ≤5 and success |
| Overlapping | Engineering sum + North sum − Engineering OR North sum, estimating Engineering ∩ North salary sum | Same 5% relative criterion | Aggregate intersection reconstruction; not individual inference |

Success is computed only for completed attack estimates. Missing estimates are
not counted as successes or failures. Relative error uses an absolute target
denominator and is unavailable below the persisted denominator threshold (1
unit). Success thresholds are parameters, stored in the run protocol; they
must be declared before execution and not changed after viewing outcomes.

## Baselines

| ID | Implementation | Interpretation |
|---|---|---|
| M0 | Raw synthetic aggregate | Unprotected utility/performance reference, not a privacy method |
| M1 | Fixed epsilon, no exhaustion cap or cache | Uncapped nominal composition comparison |
| M2 | Fixed epsilon with per-trial shared nominal budget cap | May match M1 if the cap never binds |
| M3 | Fixed epsilon multiplied by synthetic request-order factors 1.0, 0.75, 0.6, with shared cap | Synthetic role-factor comparison; not production RBAC |
| M4 | Fixed epsilon, shared cap and exact `(query identity, epsilon)` cache | Isolates exact-cache behavior from adaptive allocation |
| M5 | History-aware adaptive policy, shared cap and exact cache | Heuristic policy; not a certified DP mechanism |

Baselines share the generated workload, targets, scenario and matched trial
seeds. Each trial resets its simulated cache and budget. M5 uses configured
`epsilon_min`, `epsilon_max`, risk penalty α, budget-use penalty γ and risk
weights recorded in the protocol. The validation profile is α=0.10, γ=0.05,
epsilon floor 0.1 and configured fixed-epsilon ceiling; do not tune it using
validation results. Identical results between baselines can be expected when
their policy or cache behavior is not exercised; no result should be forced to
differ.

## Metrics

- **Attack success rate:** successful estimates / completed attack estimates.
- **Inference MAE/RMSE:** absolute/squared error between reconstructed attack
  target and synthetic ground truth, aggregated over completed trial
  estimates. This is distinct from aggregate query-answer error.
- **Aggregate MAE/RMSE:** absolute/squared error between each answered
  aggregate output and its true synthetic aggregate. The current metrics
  version identifies pooled request-level RMSE; the mean trial RMSE is also
  stored separately.
- **Relative error:** `abs(estimate - truth) / abs(truth)` when `abs(truth) >=
  1`; otherwise unavailable. UI percent values multiply the fraction by 100.
- **Answerability:** answered generated legitimate requests / generated
  legitimate requests. In these fixed valid workloads, the measured rejection
  category is budget exhaustion. Invalid SQL, unauthorized, unsupported and
  execution-failure rates are explicitly not measured by the synthetic engine.
- **Cache rate:** exact cache hits / generated requests. A hit reuses a stored
  draw and contributes zero new nominal charge; distinct releases are counted
  separately.
- **Nominal epsilon:** sum of charges for independent simulated releases.
  Per-trial budgets reset; run-level utilization is normalized to the initial
  budget per trial. It is nominal and uncertified, not a formal privacy loss.
- **Timing:** monotonic-clock in-process synthetic engine timing. It is not
  production SQL/API latency or concurrent service throughput. Component
  timing and persistence flush timing have separate scope; final DB commit
  duration is not included in the engine's `persistence_ms` field.
- **Memory:** any estimated dataset size is a shallow estimate, not peak
  process memory.

Missing metrics are represented as unavailable/null rather than measured
zero. Binary attack-success proportions use a 95% Wilson interval derived from
the stored integer success and attempt counts. Continuous summaries report
trial-level mean, median, sample standard deviation, and a 95% interval (small
sample Student-t critical values through 31 observations; normal-limit
approximation afterward). These intervals describe uncertainty under the
observed sampling model; they do not correct design bias or prove privacy.

## Paired statistical comparisons

Comparisons are within a single run and pair baseline trials only when their
trial IDs and persisted seeds match the protocol. There is no unpaired fallback.
The default reference is M1; comparisons against M0 are descriptive because
M0 is unprotected. Binary outcomes use the exact two-sided McNemar test and a
paired bootstrap interval for risk difference. Continuous outcomes use a
paired sign-flip test (exact for up to 16 pairs, otherwise seeded Monte Carlo
with 10,000 draws), percentile bootstrap confidence intervals (4,000
resamples), and paired Cohen's `dz` when the difference standard deviation is
nonzero. Holm correction is applied within each metric across contrasts to
the reference. Fewer than 20 complete pairs are exploratory and do not receive
an inferential significance label.

The sign-flip test relies on exchangeability and symmetric differences under
the null; bootstrap inference assumes observed pairs represent the target
evaluation population. McNemar uses paired binary outcomes and its null
assumption for discordant pairs. A zero-variance paired effect size is
undefined. Statistical significance, when reported, is not practical
importance, external validity, or a DP guarantee.

## Quality and evidence

The quality classifier distinguishes `valid_completed`,
`completed_with_warnings`, `partial`, `invalid`, and `failed`. The read-only
integrity validator checks available arithmetic, metric states, evidence,
trial coverage, release/cache counts, epsilon totals and protocol metadata.
Historical rows lacking evidence are `UNVERIFIABLE`; no missing data is
imputed. A quality pass only means checks supported by the persisted evidence
were satisfied.

Runs persist protocol/configuration, per-baseline metrics, per-trial
measurements, request outcomes and minimal synthetic target/inference evidence
for authorized owner review. Raw employee rows and aggregate outputs are not
persisted. See [`RESEARCH_PROTOCOL_V2.md`](RESEARCH_PROTOCOL_V2.md),
[`RESEARCH_METRIC_INTEGRITY_AUDIT.md`](RESEARCH_METRIC_INTEGRITY_AUDIT.md),
and [`EXPERIMENT_REPRODUCTION.md`](EXPERIMENT_REPRODUCTION.md) for version and
operator details.
