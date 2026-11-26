# Final reproducibility checklist

Audit date: 2026-11-26. Statuses describe this workspace and the repository
artifacts inspected; a documented procedure is not evidence that a campaign
was executed.

| Area | Status | Evidence / remaining action |
|---|---|---|
| Repository/source identity | **PARTIAL** | A Git repository and publication baseline are now present. Historical runs remain unbound to a source commit; record the current commit and dependency manifest with future cited runs. |
| Installation instructions | **PASS with caveat** | README and reproduction guide provide PowerShell commands. Python install resolves ranges rather than an exact lock. |
| Frontend dependency resolution | **PASS** | `frontend/package-lock.json` exists (lockfile v3); React and React DOM declarations now pin the versions in the lockfile. Reproduce with `npm ci`. |
| Backend dependency resolution | **PARTIAL** | `backend/requirements.txt` constrains major ranges but is not exact-pinned; no Python lockfile is present. |
| Environment configuration | **PASS with operator care** | `.env.example` documents database, JWT, CORS and Vite URL settings. Use a disposable DB and nonpublished secret. |
| Synthetic dataset generator | **PASS** | `synthetic-employee-generator-v1`; deterministic seeded Python `random.Random`; API-supported sizes 5K/25K/100K. Generator helper additionally allows 500K, but experiment API rejects it. |
| Protocol versioning | **PASS for new runs** | `privacyguard-research-protocol-v2` is serialized with run configuration. Historical records are not retrofitted. |
| Dataset/trial seeds | **PASS for recorded runs** | Dataset seed, trial seed strategy and generated trial schedule are persisted and shared across baselines. Timing is inherently environment-sensitive. |
| Scenario definitions | **PASS for Protocol V2 runs** | Difference, repeated, scripted narrowing and overlap have explicit target/estimator/success rules. They are not interchangeable attack objectives. |
| Baseline definitions | **PASS for current version** | M0–M5 definitions are versioned; older B0–B4 records use legacy mapping and must retain historical interpretation. |
| M5 policy configuration | **PASS when present in protocol** | α, γ, epsilon bounds, weights and policy identifier are persisted. Locked validation profile α=.10, γ=.05; do not tune on validation runs. |
| Privacy accounting assumptions | **PASS as disclosed, not certified** | `nominal_uncertified`; no complete formal DP guarantee. Mechanism sampler/adaptive composition limitations are documented. |
| Metrics and missing values | **PASS for current metric version; historical caveats** | `comparative-metrics-v4`, metric states, Wilson binary intervals and integrity checks. Legacy metrics may be `UNVERIFIABLE`; null must not be interpreted as zero. |
| Statistical testing | **PASS with assumptions** | Paired within-run McNemar/sign-flip tests, bootstrap intervals and Holm correction; minimum 20 complete pairs for inferential label. Assumptions and limitations documented. |
| Persistence and ownership | **PASS by implementation** | `experiment_runs` and `experiment_results` JSON records; retrieval/export require `experiments:run` and are owner-scoped. Tests use isolated SQLite fixtures. |
| CSV export | **PASS by implementation** | Owner-authorized endpoint exports configuration/protocol and safe per-trial/request measurement evidence; it excludes raw aggregate outputs. |
| Locked validation runner | **PASS by source/test coverage** | `backend/scripts/run_validation_campaign.py` checks identity/permission, prompts hidden password, requires exact confirmation, submits one request per scenario, and avoids automatic retry. It was not run in this audit. |
| Historical experiment records | **NOT RECHECKED in this audit** | No DB operation was performed. Prior status documentation reports runs #1–#13 preserved; this audit makes no new live DB claim. |
| Automated verification | **PASS** | The original audit ran backend 164 tests and frontend 37 tests. Publication preparation re-ran the backend suite (178 passed) and frontend suite (46 passed), Python compilation, frontend build, and dependency consistency checks in an isolated project virtual environment. No research run was submitted. |
| Browser/live-service QA | **NOT PERFORMED** | This is an artifact and automated reproducibility audit; no browser was accessed and no services/campaign were started. |

## Remaining artifact gaps

- There is no exact Python dependency lock. A fresh backend install can resolve
  different versions within `requirements.txt` ranges.
- Historical experiments are not bound to Git commit identity. Bind future
  cited runs to a commit and dependency manifest; do not imply that the new
  publication baseline identifies the source of old runs.
- The run protocol captures Python/platform, seeds and code-defined version
  strings, but not a complete OS build, CPU/memory inventory, BLAS/runtime
  details, or dependency snapshot at the time each historical run was created.
- Literature records are source-linked but require a final researcher-led
  citation/page/table audit before publication. Do not treat the application
  literature list as a systematic literature review.
- The full locked campaign was not executed or reverified as part of this audit;
  this document validates artifacts and automated commands, not campaign
  results or current database contents.

## Missing or incomplete documentation

1. **Exact Python environment lock and historical environment capture:** the
   current constraints and one current-machine snapshot do not prove which
   transitive packages were active when each saved run was made.
2. **Source revision linkage:** runs store implementation version strings, but
   the workspace lacks Git metadata and historical run records do not provide
   a source commit/archive checksum.
3. **Hardware and runtime manifest per run:** protocol records Python/platform,
   but not CPU, memory, OS build, BLAS details or dependency versions at run
   time. This particularly limits interpretation of timing.
4. **Prospective power/sample-size rationale:** the protocol sets 20 pairs as
   the inferential-label floor, but this is not a workload-specific power
   analysis or justification that 20 trials detects a scientifically relevant
   effect.
5. **Independent literature-source audit:** citations are stored, but a final
   paper author should check each numerical/contextual entry against its cited
   page/table and record any corrections through the controlled data source.
6. **Independent clean-machine reproduction record:** commands are documented
   here, but a second researcher has not executed them in a clean environment.

## Required submission actions

1. **Submission blocker:** bind each cited run to its actual source revision
   or immutable archive checksum and record the Python dependency set used at
   run time. The new publication baseline does not retroactively identify old
   runs.
2. **Submission blocker:** attach the persisted Protocol V2 JSON and
   owner-authorized CSV exports for each cited run; rerun the read-only
   integrity validator on copies and archive its output.
3. **High priority:** ensure every paper table reports run ID, scenario,
   baseline, numerator/denominator, units, interval, quality status and
   whether the measurement is synthetic, calibration or locked validation.
4. **High priority:** have a second researcher reproduce a representative run
   against a disposable database and record environment/runtime differences.
5. **Before statistical claims:** provide a prospective power/sample-size
   justification and ensure all compatibility, pairing and multiplicity rules
   were declared before analyzing the validation results.
6. Have a researcher verify literature citations against source pages and keep
   all claim language within [`RESEARCH_LIMITATIONS.md`](RESEARCH_LIMITATIONS.md).
