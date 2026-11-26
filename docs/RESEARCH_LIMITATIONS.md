# Research limitations and claim boundaries

This document lists limitations that affect reproducibility or interpretation.
It is not a formal security certification.

## Privacy guarantee and accounting

- The production finite-precision Laplace sampler has no established formal
  pure-ε or approximate (ε,δ) bound in the sampler audit. A seeded sampler is
  used only in synthetic experiments.
- The M5 history/risk-dependent epsilon policy is heuristic and has not been
  proved as an adaptive DP mechanism. A heuristic risk score is not a privacy
  guarantee or calibrated attack probability.
- Ledger and experiment epsilon values are `nominal_uncertified`. Summing
  epsilon is not a certified end-to-end guarantee until the component
  mechanisms and adaptive composition assumptions are proved.
- The supported privacy accounting scope is shared per dataset; it does not
  establish protections outside the documented record-level add/remove
  adjacency and supported aggregate assumptions.

## Evaluation scope

- Experiments use synthetic in-memory employee data, not the registered
  application database, production records or real enterprise workloads.
- Attacks are fixed scripts. Narrowing is not interactive. Overlap and repeated
  query variants are controlled workload abstractions, not general adversary
  models. Membership inference is not evaluated.
- Attack success is scenario-specific threshold crossing. Difference
  evaluates a synthetic individual contribution; repeated and overlap evaluate
  aggregate reconstruction. Success rates must not be described as one common
  individual inference metric across scenarios.
- M0 is raw and unprotected. M1/M2 can match when the M2 cap does not bind;
  M1/M4 can match when exact repeated requests do not hit cache; M5 can match
  fixed baselines if its signals do not alter the proposal.
- The locked α=0.10, γ=0.05 policy profile is a provisional calibration
  selection. It must not be retuned on validation runs.
- Historical records may lack Protocol V2 evidence, exact seeds or versioned
  aggregation fields. The integrity assessment can report `UNVERIFIABLE`; it
  does not reconstruct omitted evidence or rewrite history.

## Statistics and performance

- Trial count is limited (API maximum 30). Results at small n are exploratory;
  multiple testing is adjusted only within each metric family of within-run
  contrasts to the selected reference.
- Paired sign-flip inference depends on exchangeability and symmetric
  differences under the null. Bootstrap intervals depend on the observed trial
  sample. These assumptions do not imply generalization beyond the synthetic
  protocol.
- Engine timing is in-process synthetic runtime, not production SQL middleware
  or API latency. There is no actual concurrent API throughput benchmark.
- Dataset-memory reporting is approximate and does not measure process peak
  memory. Production DB commit duration is not included in synthetic engine
  latency.
- Experiment execution is synchronous. Large runs can be slow and are bounded
  by API validation; no background-job facility is implemented.

## Platform and deployment

- SQLite is the development default. PostgreSQL driver/Alembic dependencies
  are present, but production PostgreSQL setup, migration execution and
  operational behavior have not been established by this audit.
- Backend dependencies use compatible ranges without an exact lockfile. A
  fresh installation can resolve different package versions. Frontend npm
  dependencies are lockfile-backed.
- Runs created before repository initialization are not bound to a source
  commit; future runs should archive `git rev-parse HEAD` and the dependency
  manifest with the protocol evidence.
- Browser visual QA and live service execution were not part of this document
  audit. Automated tests/build do not substitute for those checks.

## Claim language

Safe descriptions include “controlled synthetic evaluation,” “observed in this
configuration,” “nominal epsilon,” and “exploratory.” Avoid claims that
PrivacyGuard is formally DP-certified, prevents inference, outperforms all
existing systems, or has production latency/security behavior established by
these experiments.
