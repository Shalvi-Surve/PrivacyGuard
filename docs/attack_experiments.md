# Synthetic attack and comparison framework

This file is the entry point for the implemented research evaluator. The
authoritative current definitions are versioned with every new run in
[`RESEARCH_PROTOCOL_V2.md`](RESEARCH_PROTOCOL_V2.md). Use
[`RESEARCH_METHODOLOGY.md`](RESEARCH_METHODOLOGY.md) for formulas and
statistical assumptions, [`comparative_results.md`](comparative_results.md)
for interpreting the UI, and [`EXPERIMENT_REPRODUCTION.md`](EXPERIMENT_REPRODUCTION.md)
for operator commands.

## Isolation and authorization

`POST /api/experiments/runs` and the legacy
`POST /api/attacks/simulate` require `experiments:run`. Runs generate
synthetic employee rows in memory and do not query registered datasets or run
user-supplied SQL. The API stores run and baseline result JSON in
`experiment_runs` and `experiment_results`. Retrieval and CSV export are
owner-scoped and require the same permission. Persisted evidence contains
minimal synthetic target/inference evidence and request/trial measurements,
not employee rows or raw aggregate outputs.

## Current scenarios

- **Difference:** estimate a selected synthetic employee's salary contribution
  by differencing related aggregate queries.
- **Repeated:** reconstruct a population salary aggregate from repeated
  observations; exact identity repeats can reuse the same cached draw.
- **Narrowing:** fixed three-step cohort COUNT script; not interactive
  attacker-selected narrowing.
- **Overlapping:** estimate Engineering ∩ North aggregate through Engineering
  SUM + North SUM − (Engineering OR North) SUM. The current estimator uses all
  three observations.

The objectives differ. Repeated/overlap are aggregate reconstruction, while
difference is a synthetic contribution-inference demonstration. None is
membership inference. Success thresholds are predeclared configuration and
persisted with the protocol. Only completed estimates enter the success
denominator.

## Baselines and accounting

New runs use M0–M5. M0 is unprotected raw reference; M1 fixed uncapped; M2
fixed with shared per-trial cap; M3 synthetic role-factor fixed with shared
cap; M4 fixed/shared cap/exact cache without adaptive history; M5 heuristic
adaptive allocation/shared cap/exact cache. Old B0–B4 rows retain their
historical interpretation and are not rewritten.

The experiment sampler is deterministic and used only by the synthetic
evaluator. Epsilon totals are nominal and uncertified. The production sampler
is separate. The M5 policy is heuristic and is not established as an adaptive
DP mechanism. A cache hit reuses one stored output and incurs no new simulated
charge; each trial resets its synthetic cache and budget.

## Current measurement scope

The current metrics version records attack/error counts and summaries,
Wilson intervals for binary success, query answerability and budget rejections,
nominal epsilon, independent releases, exact cache hits, risk/adaptive signals,
and synthetic engine timing. It also records request/trial evidence for
read-only validation and within-run matched comparisons. Production SQL/API
latency, concurrent middleware throughput, interactive attacks and reliable
peak-memory usage are not measured. Do not present synthetic engine runtime as
production service performance.

## Interpretation and legacy data

The integrity validator does not update persisted rows. Missing historical
protocol or trial evidence is surfaced as `UNVERIFIABLE`, not imputed. A
quality state indicates evidence completeness under implemented checks; it is
not a privacy proof. M1 and M2 may match when the budget cap does not bind;
M1 and M4 may match when exact cache reuse is not exercised; M5 may match a
fixed baseline if its inputs leave the same allocation. Similarity is not a
reason to manipulate workloads or outcomes.
