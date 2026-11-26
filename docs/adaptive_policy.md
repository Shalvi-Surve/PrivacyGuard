# Adaptive privacy policy and accounting boundary

## Scope and guarantee status

The current implementation is an experimental policy allocator with a nominal
epsilon ledger. It does not certify the complete pipeline as differentially
private: the production finite-precision Laplace sampler has no established
formal pure-ε or (ε,δ) bound, and the history-adaptive allocation procedure has
not been proved as an adaptive DP mechanism. `nominal_uncertified` describes
what the ledger sums; it is not certified privacy expenditure. Risk scores are
policy heuristics, not privacy guarantees or calibrated attack probabilities.

## Query risk signals

Each input is normalized to `[0,1]`. The backend uses these bounded proxies:

* `S_q = min(Δf / 300000, 1)`, where `Δf` is the configured global sensitivity
  for the supported COUNT or bounded SUM under add/remove-one-record
  adjacency. COUNT has sensitivity 1; salary SUM has 300000; performance-score
  SUM has 5. This scaling is a policy normalization, not a statistical risk
  estimate.
* `D_q = 0.75` if selected/referenced columns include salary,
  performance_score, gender, or age, otherwise `0.35`. These are fixed policy
  labels and do not alter the mathematical sensitivity.
* `H_q` is the maximum Jaccard similarity between current referenced column
  names and those in the most recent 100 successful protected and up to 100
  analysis-only events for the same dataset. These bounded per-kind windows
  are dataset-wide across users because the underlying data and budget are
  shared.
* `N_q = 0.5 min(predicate_count/4,1) + 0.5 min(shape_repeats/5,1)`. The repeat
  count compares normalized structural fingerprints in that same history
  window. It is a narrowing/repetition proxy; literal predicate values are not
  retained in this feature.
* `T_q = 0.2` for COUNT and `0.8` for bounded SUM.

The default weights are `(0.20, 0.25, 0.25, 0.20, 0.10)` and sum to one:

`R_q = 0.20 S_q + 0.25 D_q + 0.25 H_q + 0.20 N_q + 0.10 T_q`.

Thus `R_q` is bounded in `[0,1]`. History enters this score once. The allocator
does not add a second standalone history penalty.

## Nominal epsilon allocation

Let `C = spent / initial` be the validated shared dataset budget utilization,
which is in `[0,1]`. The original production policy (`query-history-adaptive-
nominal-v1`) remains unchanged with defaults `epsilon_min=0.1`,
`epsilon_max=1.0`, `alpha=0.6`, and `gamma=0.3`:

`epsilon_q = clip(epsilon_max - alpha * R_q - gamma * C,
                  epsilon_min, epsilon_max)`.

For new M5 synthetic research runs, policy `query-history-adaptive-nominal-v2`
uses the same documented risk score and linear allocation rule, with calibrated
defaults `epsilon_min=0.1`, `epsilon_max=configured fixed epsilon`,
`alpha=0.1`, and `gamma=0.05`. These coefficients mean that moving the bounded
risk score from 0 to 1 reduces the proposal by at most 0.1 epsilon, while
moving budget utilization from 0 to 1 reduces it by at most 0.05 epsilon.
Both effects are monotone and additive; the lower and upper bounds are then
applied. The policy does not raise epsilon above the configured fixed-epsilon
ceiling. The bounds and coefficients are explicit validated experiment inputs
and are persisted in the protocol per M5 run. The production route continues to
use v1 unless it is separately configured and validated.

Invalid/non-finite components, weights, penalties, epsilon bounds, and budget
metadata are rejected. The decision records its component scores, weights,
unclipped proposal, utilization, remaining budget, and policy ID in safe audit
metadata. If the selected epsilon exceeds remaining budget, a new release is
rejected; the value is not reduced to an unaffordable or unreviewed amount.
The shared per-trial budget guard in the synthetic engine remains enforced for
M2–M5. In the production query path, the atomic conditional SQL reservation is
the final concurrency guard.

The result is deterministic for the same inputs/configuration. Within each
synthetic trial, M5 selects epsilon on the first occurrence of an exact
validated query identity and pins that epsilon to the identity for the trial.
Exact repeats therefore reuse the same stored draw and incur neither another
independent release nor another nominal charge. A distinct normalized query
identity is assessed against current history and budget and can receive a
different epsilon and a separate draw. The cache key continues to include the
query identity and epsilon. This exact-repeat policy preserves consistency and
prevents epsilon drift from turning a repeated request into a fresh draw; it
does not prevent inference from distinct related queries.

## M5 development calibration (exploratory)

The previous Run 9 M5 selected mean epsilon 0.15225 with mean risk 0.58833;
the original alpha=0.6 term alone subtracts about 0.353 from a 0.5 ceiling
before cumulative utilization is applied. Its resulting aggregate MAE was
2,749,252.66 versus 682,103.63 for M1/M2/M4 on that five-trial pilot. This is
a policy-calibration signal, not evidence that reducing alpha is universally
better.

A separate in-memory development calibration used 5,000 generated rows, seed
83021, five matched trials, fixed epsilon 0.5, budget 10 per trial, and M1,
M4, and M5. Difference and identical repeated-query workloads were evaluated.
Seven coefficient pairs were compared: (0.6,0.3), (0.4,0.2), (0.3,0.15),
(0.2,0.1), (0.15,0.075), (0.12,0.06), and (0.1,0.05). No database or
persisted run was used. The predeclared exploratory selection rule required
zero budget rejections, no higher observed attack-success count than the
scenario-matched reference (M1 for difference, M4 for repeated), and pooled
M5 nominal spend between 80% and 90% of reference spend. Among eligible
profiles it selected the one with the lowest sum of scenario-level aggregate
MAE. The (0.1,0.05) profile met the pooled expenditure criterion: M5 spent
0.88008 + 0.45325 = 1.33333 epsilon per trial versus reference 1.0 + 0.5 =
1.5 (88.89%). Its repeated-workload spend alone was 90.65% of M4, slightly
above the pooled range; this is disclosed rather than hidden. It had the
lowest combined MAE among profiles meeting the pooled rule.

Observed M5 results by profile (difference / repeated; epsilon expenditure per
trial; aggregate MAE) were: original (0.6,0.3), 0.30450 / 0.21950 and
1,763,341.64 / 2,593,825.35; balanced (0.2,0.1), 0.76065 / 0.40650 and
812,404.75 / 1,400,601.88; moderate (0.3,0.15), 0.64172 / 0.35975 and
936,425.12 / 1,582,611.99; strong-moderate (0.4,0.2), 0.52327 / 0.31300 and
1,108,076.35 / 1,818,992.54; (0.15,0.075), 0.82030 / 0.42988 and
762,244.88 / 1,324,442.37; (0.12,0.06), 0.85615 / 0.44390 and
735,077.14 / 1,282,596.68; selected (0.1,0.05), 0.88008 / 0.45325 and
718,036.48 / 1,256,138.26. Scenario reference MAE was 643,604.84 for M1
(difference) and 1,138,689.33 for M4 (repeated). Observed attack success was
0/5 for all profiles and M1 in difference, and 5/5 for all profiles and M4 in
repeated; these tiny samples show no measured resistance improvement. No
profile incurred budget rejections. Exact repeat behavior after the M5 cache
correction was five independent releases and 20 exact cache hits; M4 showed
the same release/hit counts. M1 generated 25 releases for repeated requests.
Mean history lookup and risk-policy timings were on the order of 0.001 ms and
0.007 ms in this synthetic evaluator; these noisy micro-measurements do not
establish an API or production latency result. Five trials per workload are
exploratory and cannot support significance claims. These calibration
measurements were not persisted as experiment runs.

The selected coefficients are a provisional calibration default, not a claim
of optimality. They preserve a monotone risk and budget response while reducing
the v1 penalty magnitude. M5 can still differ from fixed policies and must be
validated on an independent workload; its finite-precision sampler remains
uncertified and its nominal ledger is not a formal DP guarantee.

## Privacy unit, adjacency, and composition boundary

The intended privacy unit is one employee record in the selected dataset.
The implemented query path uses add/remove-one-record adjacency. COUNT has
global sensitivity 1. For bounded SUM with each row clipped to `[L,U]`, the
absent contribution is zero, so sensitivity is `max(|L|,|U|)`. Current
configured bounds are salary `[0,300000]` (sensitivity 300000) and
performance_score `[1,5]` (sensitivity 5). The path supports only the
restricted ungrouped COUNT and bounded SUM query forms.

Accounting scope is one shared budget per dataset (`scope=dataset`,
`owner_id=NULL`), shared by every authorized user. A new persisted release and
its ledger entry are committed in the same transaction as the reserved budget;
failures roll back reservation and ledger writes. Cached exact reuse adds a
request-history/audit row but no ledger expenditure. The ledger's basic sum is
the nominal sequential-composition total for distinct newly generated
releases. Basic composition `sum(epsilon_i)` would be a valid pure-DP bound
only if every component mechanism satisfied its stated DP guarantee and the
adaptive choices satisfied the relevant conditional/adaptive composition
assumptions. Those prerequisites are not established here, so no formal
end-to-end epsilon guarantee is claimed. No approximate-DP or RDP accountant
is implemented.

## Cache and history boundaries

The lookup identity binds dataset ID/version, structural fingerprint, query
identity including normalized literal values, effective authorized role
scope, policy version, mechanism, sensitivity, clipping bounds, adjacency,
and selected epsilon. Configuration mismatches fail closed. The version bump
to `protected-release-v3-adaptive-accounting` makes older cache entries
ineligible for reuse; the next request may create a newly charged release.

History signals are intentionally safe and coarse: they use stored structural
fingerprints and referenced attribute names, not raw aggregate values or SQL
literal values. They cannot characterize arbitrary predicate overlap,
correlated attributes, auxiliary information, or every multi-query inference
attack. The Risk Analysis page remains a labeled illustrative UI and is not a
live display of the backend calculation.

## Evaluation gaps

Before claiming formal protection, replace or prove the finite-precision
sampler, establish a formal analysis of history-dependent selection and
composition, validate threat-specific history features, and compare the policy
against fixed-epsilon baselines under controlled experiments. No such
experimental result is claimed by this milestone.
