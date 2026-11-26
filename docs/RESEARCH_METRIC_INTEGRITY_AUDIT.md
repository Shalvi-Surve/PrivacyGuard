# PrivacyGuard research metric integrity audit

**Audit date:** 2026-11-26  
**Scope:** synthetic experiment engine, persisted result JSON, API serialization, metric display and read-only validation of the existing SQLite experiment records.

## Integrity and preservation boundary

The validator reads each run's `configuration` and each `ExperimentResult.metrics` JSON value. It does not update either table. API retrieval computes the report on demand; new runs also store the finding summary in that new run's configuration when the run is completed. Existing historical measurements are not rewritten. At the time of this audit the workspace had no `.git` metadata; a Git baseline was initialized later during publication preparation. Historical runs are still not bound to a source commit.

The report uses four statuses:

- **PASS**: the checked invariant is internally consistent and independently verifiable from persisted safe metadata.
- **WARNING**: a qualification or possible interpretation issue requires care; it is not by itself proof of a defect.
- **FAIL**: persisted values contradict a checkable arithmetic or structural invariant.
- **UNVERIFIABLE**: the evidence or version metadata required to check the metric was not persisted.

`PASS` is not a privacy guarantee. Nominal epsilon is not certified privacy expenditure.

## Protocol v2 addendum

This audit describes the historical and then-current implementation as of the audit date. New runs now use the separately versioned protocol in [RESEARCH_PROTOCOL_V2.md](RESEARCH_PROTOCOL_V2.md). The v3 overlap workload uses Engineering, North, and Engineering-or-North marginals in an inclusion-exclusion estimate of Engineering ∩ North. The earlier unused-North-marginal issue is corrected for new runs only; historical run definitions and measurements are unchanged. Protocol v2 also persists minimal synthetic evidence needed to recompute attack errors and classifications, and adds matched-seed paired comparisons. Historical runs without such evidence remain unverifiable and are never assigned the new interpretation.

## Metric definitions reviewed in the original audit

The entries below document the integrity audit snapshot and its historical
findings. New Protocol V2 runs use `comparative-metrics-v4`; see
[`RESEARCH_PROTOCOL_V2.md`](RESEARCH_PROTOCOL_V2.md) and
[`RESEARCH_METHODOLOGY.md`](RESEARCH_METHODOLOGY.md) for the current
definitions. Do not treat legacy run metrics as though they had v4 evidence.

| Metric | Definition and evidence | Limitation |
|---|---|---|
| Attack success | One reconstruction attempt per trial; successful if absolute reconstruction error is at most the scenario threshold. Rate is successful completed attempts divided by completed attempts. No estimate means no attempt and does not enter the denominator. | Measures the specific synthetic reconstruction objective, not generalized attack resistance. |
| Difference inference | Engineering salary SUM minus the same cohort's SUM excluding one selected synthetic employee; target is that employee's salary. Threshold is 5% of `max(abs(target), 1)`. | A controlled individual contribution inference; it is not membership inference. |
| Repeated-query inference | Mean of returned repeated full-dataset salary SUM observations; same output may be repeated by M4 cache. Threshold is 5% of the true full-dataset SUM (with a 1-unit floor). | This is aggregate reconstruction, not individual attribute inference. A 100% success result does not imply an individual was identified. |
| Narrowing inference | Final count from a fixed three-stage narrowing predicate sequence; success is absolute error at most one record. | Sequence is predefined, not chosen interactively based on previous answers. It reconstructs a cohort count, not membership or an attribute. |
| Overlap inference | Engineering salary SUM minus Engineering-and-North intersection SUM; target is Engineering outside North. Threshold is 5% of `max(abs(target), 1)`. | It is a subgroup aggregate. The generated North marginal query is currently executed but is not used by the inference formula; this is an avoidable workload cost and should be resolved under a separately versioned scenario redesign. |
| Inference MAE / RMSE | Mean absolute reconstruction error and square root of mean squared reconstruction error across trials with a completed estimate. Ground-truth values are intentionally not stored. | Arithmetic over stored trial errors is verifiable; reconstruction against source truth is not independently reproducible after persistence. |
| Relative error | `absolute_error / abs(reference)` as a fraction; unavailable for reference magnitude below 1. UI converts the fraction to a percentage and shows two decimal places. | The reference magnitude is not persisted, so saved ratios cannot be recomputed independently. |
| Aggregate MAE | Mean of per-trial means of absolute query-answer errors. Each trial's request errors include successfully answered requests only. | A budget-rejected query has no answer error and is not treated as zero error. |
| Aggregate RMSE | Current Protocol V2 / `comparative-metrics-v4` stores pooled request-level `sqrt(mean(error²))`; per-trial RMSE summaries are also available. | Historical versions did not consistently version this aggregation level; their run-level RMSE is marked unverifiable where the method is unknown. |
| Answerability / budget rejection | Answerable successful requests / all generated valid requests; budget rejection / same denominator. | Invalid SQL, unauthorized, unsupported and execution failures are not simulated and are reported as not measured. |
| Cache hits / releases / expenditure | Request status rows distinguish `released`, `cached`, `raw_unprotected`, and `budget_rejected`. Only newly generated protected outputs incur nominal epsilon. | Nominal accounting is experimental and uncertified. Exact cache reuse is measured only if at least one hit occurs. |
| Confidence intervals | Wilson score 95% interval for binary attack success. Student-t interval for continuous trial means through 31 observations, normal-limit critical value thereafter. | Small trial counts are exploratory; intervals do not establish statistical significance or correct model misspecification. |

## Baseline behavior

- **M0** returns raw synthetic aggregates and is a utility reference, not a privacy-preserving baseline.
- **M1** uses fixed epsilon without a composition cap.
- **M2** uses fixed epsilon and a per-trial shared nominal budget cap.
- **M3** applies synthetic role factors `(1.0, 0.75, 0.6)` to fixed epsilon and uses the shared cap.
- **M4** uses fixed epsilon, shared cap and exact identity/epsilon cache; it does not use adaptive history allocation.
- **M5** uses the existing history-aware heuristic epsilon policy, shared cap and exact cache.

All use matched synthetic workloads and seed schedules. M1/M2 can be numerically identical when the M2 budget does not bind. M1/M4 can be identical when no repeated identical request causes a cache hit. Equality under those conditions is expected and must not be “fixed” by forcing different outputs. M5's risk score and adaptive allocation are heuristics; neither is itself a DP guarantee.

The experiment sampler is deterministic and seeded for synthetic research only. The production sampler remains unchanged. The finite-precision production sampler and complete adaptive pipeline have no established formal end-to-end DP guarantee; all experiment expenditure is labeled `nominal_uncertified`.

## Metric and report corrections completed

- Missing and zero measurements are now represented distinctly; unmeasured error metrics remain null rather than zero.
- Relative error below the documented denominator threshold is unavailable; displayed percentages use two decimal places so small nonzero ratios do not become `0.0%`.
- The original audit introduced Wilson intervals; current Protocol V2 serializes Wilson bounds from stored success/attempt counts at read time. Legacy stored boundary intervals remain unchanged and are flagged where their historical Wald interval was zero-width at 0%/100%.
- Validator checks attack counts/rates, per-trial success threshold when evidence exists, error aggregation, cache/release/epsilon totals, request outcomes, range constraints, confidence intervals and version metadata.
- Cache consistency is not marked successful when no cache reuse occurred. Historical default-true values with zero hits are unverifiable, not retroactively rewritten.
- The historical run-level aggregate RMSE check is version-aware. An earlier validator revision incorrectly compared every legacy run to pooled request RMSE; legacy summaries may instead match the mean per-trial RMSE. These are different statistics. The validator now marks an unversioned aggregation rule unverifiable instead of reporting a false arithmetic failure.
- Integrity findings expose run ID, scenario, dataset size, baseline, metric, status, finding, expected/observed evidence, reason and suggested action. Reports are computed read-only.

## Read-only assessment of stored runs

The local SQLite file was opened using SQLite `mode=ro`; no update, seed, migration or experiment execution was performed.

| Run | Scenario | Report | Assessment |
|---:|---|---|---|
| 1–3, 6 | Difference | WARNING | Legacy B0–B4 metric records lack complete versioned definitions and sufficient per-trial attack evidence. No arithmetic FAIL remained after the legacy RMSE false positive was removed. This is not proof that every historical value is correct. |
| 4–5 | Repeated | WARNING | Same legacy limitations; additionally interpret success as full-dataset SUM reconstruction, not individual inference. |
| 7 | Difference | WARNING | M1, M2 and M4 have equal observed outcomes; M2's budget did not bind (40 releases × 0.5 epsilon = 20 total across 20 trials, with 1 epsilon/trial against a 10 epsilon/trial cap); M4 had zero cache hits. Matched seeds and equal epsilon explain equality. Run uses v2 Wald intervals and lacks persisted target/error evidence for independent reconstruction. |
| 8 | Repeated-query averaging | WARNING | 20/20 trials meet the stored success definition for reconstruction of the full synthetic salary SUM within 5% tolerance. This is not evidence of individual-level inference. M1/M2: 100 releases, 0 hits, nominal epsilon 50. M4: 20 releases, 80 hits, nominal epsilon 10. M5: 40 releases, 60 hits, nominal epsilon about 6.39. The v2 100% Wald interval `[1,1]` is misleadingly zero-width; the current validator flags this historical method. |

After corrections, the read-only report found **zero demonstrable arithmetic FAILs** across Runs #1–#8. All remain WARNING because of verifiability and interpretation limits; that status must not be presented as a pass or validation of the privacy guarantee. The detailed per-run report is also available from the authenticated saved-run API response.

## Remaining research limitations

1. Historical rows do not persist target truth, inferred estimate or scenario threshold in all versions. Errors and binary success cannot be independently reconstructed for those rows.
2. Relative-error reference values are not persisted; saved relative ratios cannot be independently recalculated.
3. The overlapping workload executes a North marginal query unused in the current inference formula.
4. Query-history overlap in M5 is a coarse synthetic feature-overlap heuristic and does not model arbitrary SQL predicate equivalence, difference attacks over unrestricted predicates, or a fully adaptive adversary.
5. The experiment engine is sequential synthetic code. Its timing is not production SQL/API latency or a concurrency benchmark.
6. Student-t intervals assume a suitable sampling model; the campaigns assessed in this audit are exploratory. At the time of this audit, paired tests and multiplicity correction were not implemented; protocol v2 adds them for new, seed-matched runs as documented in [RESEARCH_PROTOCOL_V2.md](RESEARCH_PROTOCOL_V2.md).
7. The production finite-precision sampler and end-to-end composition pipeline are not formally certified. No pure-ε or approximate `(ε,δ)` claim should be made from these results.

The next research step should be a versioned scenario/metric protocol that persists enough non-sensitive validation evidence to reproduce attack-error checks, redesigns the overlap workload to use all generated observations, and runs paired multi-seed campaigns with a pre-registered success definition. Historical runs should remain immutable and separately labeled.
