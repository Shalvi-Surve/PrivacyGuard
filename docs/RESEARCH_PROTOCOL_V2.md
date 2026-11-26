# PrivacyGuard synthetic research protocol v2

**Protocol identifier:** `privacyguard-research-protocol-v2`  
**Metric definitions:** `comparative-metrics-v4`  
**Workload definitions:** `synthetic-workloads-v3`  
**Attack definitions:** `synthetic-attacks-v3`

## Scope and preservation

Protocol v2 applies only to newly created synthetic runs. Its complete protocol object is stored in the run's existing JSON configuration field. Historical runs are never retroactively assigned v2 semantics and remain assessed under their recorded fields and the read-only integrity validator. No database schema migration is required. Experiments use generated synthetic employee records only; registered application datasets are not read. Run retrieval and CSV export remain owner-scoped and permission protected.

The experiment sampler is seeded for reproducible synthetic evaluations and is separate from production randomness. No result in this protocol establishes a formal end-to-end Differential Privacy guarantee. Epsilon expenditure is **nominal and uncertified**.

## Protocol contents

The persisted protocol records its version; scenario identifier and objective; attack estimator and success rule; synthetic dataset identifier, generator version, row count and seed; workload definition, query mode, repetitions, history depth, ablation and query limit; configured tolerances; baseline IDs and relevant epsilon, budget, role-factor, cache and adaptive-policy settings; trial count, seed strategy, per-trial seeds and noise-seed derivation; mechanism and metric versions; denominator and inclusion rules; statistical methodology; and Python/platform information available at execution time.

For M3, the base fixed epsilon is stored alongside the role factors, because the actual role-specific allocation is derived from that base. M0 remains an unprotected utility reference. M4 isolates exact release caching from adaptive allocation; M5 is the history-aware adaptive policy.

## Attack objectives and criteria

The scenario protocol defines the target, estimator, success rule and interpretation before a run:

| Scenario | Objective | Estimator / success rule | Interpretation |
|---|---|---|---|
| Difference | Infer one selected synthetic employee's salary contribution | Engineering SUM minus Engineering SUM excluding the selected synthetic row; success when absolute error is at most `relative_tolerance × max(abs(target), 1)` | Individual contribution inference, not membership inference |
| Repeated | Reconstruct the full synthetic salary sum | Mean of answered repeated observations; the same relative criterion | Population aggregate reconstruction, not individual attribute inference |
| Narrowing | Reconstruct the cohort count under a fixed query script | Final predeclared narrowed COUNT; success when absolute count error is at most the configured count tolerance (default 1) | Fixed scripted narrowing, not interactive attack adaptation |
| Overlapping | Reconstruct Engineering ∩ North salary SUM | Engineering SUM + North SUM − (Engineering ∪ North) SUM; same relative criterion | Aggregate intersection reconstruction |

The overlap workload now uses all three executed observations. Its previous Engineering-minus-intersection formulation and unused North marginal are replaced under the new attack/workload versions. Existing persisted workloads remain unchanged.

Only completed estimates enter the attack success denominator. A trial without a completed estimate is unmeasured, not a failure or success. The protocol stores minimal synthetic evidence per trial: synthetic evidence scope, target reference, target value, inferred value, absolute and relative errors, relative denominator, threshold and success flag. It does not persist raw query answers or employee rows. This evidence is returned only through owner-authorized run retrieval/export.

## Paired comparisons

Within-run contrasts pair baseline trial `i` only when both rows contain the same persisted protocol trial seed. Different seeds or incomplete schedules produce an incompatible/unavailable assessment rather than an unpaired substitute. Runs can be compared for protocol compatibility by exact equality of scenario, dataset, workload, attack parameters, trial schedule, privacy parameters and metric definitions; no cross-run inferential UI is enabled yet.

- Binary attack success: exact two-sided McNemar test; paired bootstrap interval for the risk difference.
- Continuous trial outcomes: paired sign-flip randomization test (exact through 16 pairs; deterministic 10,000-draw Monte Carlo above 16); paired percentile bootstrap 95% interval with 4,000 resamples; paired Cohen's `dz` where difference SD is nonzero.
- Multiplicity: Holm adjustment within each metric across comparisons to the selected reference.
- Fewer than 20 complete pairs are labeled exploratory and receive no inferential significance label. At 20 or more, p-values are still conditional on the assumptions shown with each result; this is not a claim of practical importance or generalization beyond the synthetic workload.

The sign-flip procedure assumes exchangeability and symmetric differences under the null. Bootstrap intervals rely on the observed pairs representing the evaluation population. McNemar assumes paired binary outcomes and equal probability for discordance under its null. Paired effect size is undefined for zero-variance differences. Missing outcomes reduce `n_pairs`; they are not imputed.

## Quality control and limitations

Run quality is classified as `valid_completed`, `completed_with_warnings`, `partial`, `invalid`, or `failed`. Missing protocol/evidence, limited trial count, validation warnings, or incomplete outputs are visible; QC does not fill missing metrics. The integrity assessment remains read-only for historical results.

M0 is not a privacy-preserving competitor. M1/M2 may match when the shared cap does not bind. M4 only differs when repeated exact requests exercise its cache. M5 may legitimately match another baseline if the selected history/policy inputs do not change allocation or outcomes. The policy is heuristic and the seeded finite-precision experiment sampler has no established formal DP guarantee. These results do not show interactive attacker adaptation, real database middleware latency, concurrent API throughput, or production data behavior.

## Safe schema/application procedure

Protocol v2 uses existing JSON columns; no migration or production database write is part of this change. Tests use temporary SQLite databases. If future evidence size or indexing needs require schema changes, first prepare and validate a non-destructive migration against a copy and obtain explicit review before applying it to the project database.
