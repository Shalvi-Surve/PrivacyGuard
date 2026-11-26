# Project status

## Live overview dashboard — 2026-11-21

- Traced the Overview service call to `GET /api/dashboard/summary`; the
  operations router registers that exact path and `main.py` includes the
  router. The frontend path and Vite `/api` proxy target are aligned. The
  generic 404 message therefore indicates the running backend instance is
  stale or the configured `VITE_API_BASE_URL` targets a different API; the
  repository's route itself was not missing. The client now includes the
  failing path in its 404 message to make that mismatch easier to diagnose.
- Reworked the existing summary endpoint to use SQL-side counts/grouping and
  permission-scoped datasets, query history, budgets and audit activity.
  Cached requests count as requests, but the release KPI counts unique persisted
  outputs for administrators. Regular roles see their own query history and
  audit events, while shared budget information follows the existing dataset
  budget permission model. Missing budget rows return nulls.
- Connected the authenticated Overview to persisted KPIs, daily decisions,
  decision distribution, recent query details, budget status, safe audit
  descriptions and operational capability signals. Added loading, empty,
  refresh, retry and error states. Illustrative values remain confined to the
  explicitly labelled preview mode; authenticated metrics never fall back to
  those values. The budget and decision charts now use returned values.
- Added backend coverage for route registration/auth dependency, role scoping,
  empty data, missing budgets, audit safety, and a protected COUNT → cached
  repeat workflow that verifies expenditure is charged once. Frontend coverage
  checks persisted KPI/chart/activity/budget rendering, empty and error states,
  retry controls, and the service path.
- Verification: backend suite 38 passed; frontend suite 16 passed; production
  build passed; Python `compileall` passed. The protected COUNT/repeat/dashboard
  workflow test verified request totals 1→2, unique release count stays 1, and
  shared budget expenditure remains unchanged on cache reuse. Browser visual
  inspection remains pending: the computer-use bridge failed to initialize
  (`failed to write kernel assets: The system cannot find the path specified`).

## Dashboard runtime regression repair — 2026-11-21

- Confirmed the reported 404 was caused by the live backend process, not a
  frontend/backend path mismatch: PID 29208 was running `uvicorn app.main:app`
  on port 8000 from November 20, and that process's OpenAPI omitted both
  dashboard paths. The repository registers `/api/dashboard/summary`, the
  frontend calls that exact path, and Vite proxies `/api` to port 8000.
- Replaced the stale process with the current source on port 8000, retaining
  the existing default `backend/adaptive_dp.db`. `/health` returned ready,
  `/docs` returned 200, OpenAPI listed `/api/dashboard/summary`, and an
  unauthenticated dashboard request returned 401 rather than 404.
- A full authenticated synthetic COUNT and cache-repeat workflow against the
  current source on an isolated SQLite database returned: first request
  `RELEASED`, second `CACHED`; request count increased 1→2, unique releases
  stayed at 1, and spent/remaining epsilon did not change on the cached repeat.
  The empty dashboard and role isolation are covered in backend tests.
- Regression checks: backend 38 passed, frontend 16 passed, build passed, and
  Python compilation passed. Browser visual verification remains pending; the
  computer-use bridge could not initialize in this environment.

## Protected-query hardening audit — 2026-11-21

- Confirmed the active release path uses add/remove-one-record adjacency:
  COUNT sensitivity is 1; clipped salary SUM sensitivity is 300,000 and
  performance-score SUM sensitivity is 5. Clipping occurs inside the aggregate
  expression before summation. The inverse-CDF Laplace scale is sensitivity /
  epsilon. Ordinary releases use a cryptographic random source; seeded sampling
  is separated into an explicitly named synthetic-experiment helper.
- Fixed a floating-point endpoint defect in the secure Laplace sampler: the top
  53-bit draw could round to exactly 0.5 and raise a domain error. Uniform
  samples are now clamped to the representable open interval before the
  transform.
- Hardened release identity with dataset ID/version, canonical fingerprint,
  literal-sensitive normalized query digest, effective authorization scope,
  mechanism, sensitivity, clipping bounds, adjacency and policy version. The
  stored configuration digest also includes actual epsilon. Retries reuse the
  original output and epsilon with no additional ledger charge; different
  static configurations or authorization scopes cannot reuse it. All users
  still draw from the same dataset budget.
- Verified reservation, output, history, ledger and audit share a transaction.
  Added coverage for rollback after execution failure, sanitized failure text,
  concurrent insufficient budget, budget exhaustion, concurrent different and
  identical queries, cache charging, and history ownership. Responses and
  history contain no raw aggregate value; errors and audit metadata contain no
  database error text or credentials.
- Corrected stale README/accounting documentation to describe the implemented
  SQLite workflow and its limits. The adaptive history-based epsilon selection
  remains heuristic; a formal proof for the complete adaptive pipeline is not
  established. Dataset metadata version currently starts at 1; data mutation
  and version bumping are not implemented.
- Verification on 2026-11-21: backend `python -m pytest -q` — 33 passed;
  frontend `npm test` — 13 passed; `npm run build` — passed; Python
  `compileall` — passed. Browser automation could not initialize because its
  kernel assets path was unavailable, so visual browser verification and
  viewport inspection remain pending.

## Research prototype vertical slice — 2026-11-20

- Added reproducible synthetic employee dataset creation (5k–500k rows),
  dataset metadata and role grants, and role-scoped listing. Generation is an
  explicit administrator action; it does not run at startup.
- Added a dataset-scoped protected aggregate route for the restricted SQLGlot
  COUNT/SUM subset. Execution compiles validated predicates to SQLAlchemy
  expressions and scopes every query by dataset ID; it does not run submitted
  SQL text.
- Protected COUNT uses add/remove sensitivity 1. SUM is limited to configured
  salary/performance bounds and clips each contribution before summing. The
  Laplace mechanism uses a cryptographic random source in normal release mode.
- The release flow derives a structural heuristic from same-dataset history,
  allocates epsilon, conditionally reserves the shared dataset budget, executes
  the aggregate, stores only the protected output, then commits history, ledger
  and audit data together. An exact dataset/query repeat reuses that same noisy
  release without another charge. Failed execution rolls the transaction back.
- Connected Dataset Management and Query Console to dataset list/generation,
  analysis, and protected execution APIs. The console distinguishes SQL
  analysis from execution and labels the returned value as a protected query
  output, not an experimental finding. Offline state leaves the editor visible.
- Verification: backend suite 23 passed; frontend suite 12 passed; frontend
  TypeScript and Vite production build passed. A targeted SQLite integration
  suite covers protected COUNT, cache charging, rejection, role isolation,
  predicate OR semantics and deterministic synthetic generation.
- Vite started at `http://127.0.0.1:5175/`; an HTTP server check is pending.
  Desktop browser automation failed during helper initialization, so actual
  visual rendering, console inspection, and viewport checks have not been
  verified.

### Still pending after this vertical slice

- CSV import/validation, PostgreSQL configuration/connectivity, Alembic
  migrations, and other synthetic domains.
- History retrieval, dedicated budget/risk/audit APIs and connected pages,
  attack simulation, reproducible experiment execution, live dashboard metrics,
  protected CSV/PDF exports, and faculty walkthrough.
- PostgreSQL and concurrent release behavior have not been tested. The risk
  score is a heuristic, not a calibrated attack-risk result. SUM bounds are
  specific to the two configured synthetic employee attributes. No completed
  attack defense or experimental result is claimed.

## Connectivity repair update — 2026-11-20

- Diagnosed the reported login warning: the frontend's configured default API
  origin matched FastAPI at `127.0.0.1:8000`, but no process was listening on
  that port when inspected. The project root had no `.env`; the backend's
  existing safe development fallback selected SQLite. This was a stopped
  backend, not an incorrect login payload or CORS rejection.
- Started FastAPI and verified `/health`, registered API paths, invalid-login
  401, successful seeded login, `/api/auth/me`, and protected COUNT analysis
  over localhost HTTP. The database used for this check was local SQLite.
- Added same-origin Vite proxying for `/api` and `/health`, configurable with
  `VITE_API_BASE_URL`, explicit local development CORS origins, and exact
  production origins through `CORS_ALLOWED_ORIGINS`.
- `/health` now reports process liveness separately from database availability;
  development schema-creation failures are logged without taking down the
  health route. The login and application shell offer retry when connectivity
  is unavailable.
- Baseline before this repair: frontend 3 tests passed; backend 15 passed.
  After changes: frontend 12 tests passed; backend 18 passed; production
  frontend build passed.
- PowerShell verified the frontend root and module entry at
  `http://127.0.0.1:5255/`, plus same-origin `/health` and login proxy paths.
  Seeded login, `/me`, COUNT/SUM analysis, invalid credentials, unsupported
  query rejection, missing authentication, and logout were exercised over the
  Vite proxy. Browser automation could not initialize, so browser console and
  1440×900 / 1366×768 / 390×844 visual checks remain unverified.

## Current milestone: 2 — Database and authentication

The workspace was empty on 2026-11-17. No existing application files, Git repository, remote, dependencies, or environment configuration were present. Python 3.11.9, Node.js 24.18.0, and npm 11.12.0 are available. PostgreSQL was not detected or reachable locally.

The supplied research material describes a query-history-aware adaptive Differential Privacy middleware. It frames the contribution as system integration and evaluation, not a new DP mechanism. Claimed benefits remain hypotheses pending actual experiments.

### Completed

- Inspected the workspace and found no existing implementation to preserve.
- Reviewed the supplied development prompt, presentation, and master sheet.
- Added the initial project structure, local configuration examples, and architecture/roadmap documentation.
- Added a small FastAPI health endpoint and a React/Vite application shell.
- Installed backend and frontend dependencies. The frontend production build succeeds; the backend imports and Python bytecode compilation succeeds.
- Added SQLAlchemy models for users, RBAC, dataset budgets, query history, audit and experiment records.
- Added Argon2 password hashing, expiring JWT helpers, login/logout/profile routes, a permission dependency, and a demo seeder requiring `DEMO_PASSWORD`.
- Added authentication checks, SQL analyzer checks, privacy mechanism checks, shared-budget checks, and policy checks; the current suite reports 15 passing tests.
- Added SQLGlot analysis for restricted COUNT/SUM statements, structural fingerprints, and `/api/queries/analyze` behind `queries:submit`.
- Added Laplace noise and COUNT/bounded-SUM sensitivity/clipping helpers.
- Added an atomic conditional-update accountant for a shared dataset budget and ledger, with over-budget rejection.
- Added a normalized weighted risk assessment and clipped adaptive-epsilon policy helper; these remain unconnected to query history and release processing.
- Replaced the frontend placeholder with the PrivacyGuard sign-in, dashboard shell, client-side navigation, query analyzer screen, offline messaging, and responsive layouts. Preview values are explicitly illustrative.
- Added three server-rendered React smoke tests; frontend tests and production build pass.

### Pending

- Inspect the running frontend in a real browser at desktop and mobile sizes; browser automation could not initialize in this environment.
- PostgreSQL is not available in this environment: `psql` is not on PATH and localhost port 5432 did not respond. The Windows service inventory was inaccessible.
- Add Alembic migrations and synthetic enterprise datasets.
- Expand RBAC across the required table/column/query policies and add protected admin user management.
- Implement parameterized SQL execution against PostgreSQL, then test it when a server is available.
- Connect aggregate execution to DP, atomic shared-budget reservations, release caching, query history, risk allocation, and audit.
- Continue through Milestones 2–10 in `IMPLEMENTATION_ROADMAP.md`.

No end-to-end DP release, attack defense, or research result is claimed. The unit tests cover authentication helpers, SQL analysis, budget accounting, policy, and mechanism helpers using in-memory SQLite where applicable. PostgreSQL concurrency and full HTTP integration remain unverified.

## Dashboard RBAC recovery — 2026-11-21

- The active `/api/dashboard/summary` route authenticates through the existing
  JWT `current_user` dependency, then requires `history:read_all` or
  `history:read_own`. The active SQLite database had an active `admin` user
  assigned to `administrator`, but that role had neither permission. The
  resulting 403 was a stale role-permission association, not a bad token or
  missing route.
- Added a shared source role policy and `backend/scripts/sync_rbac.py`. The
  script is additive and idempotent: it creates missing permission records and
  source-defined role associations, while leaving users, credentials, role
  memberships, dataset grants, and application records unchanged. It was run
  against the existing SQLite database; four permissions and thirteen role
  associations were added. The regular demo seeder was not run because it
  intentionally rotates demo passwords.
- The administrator role now includes the dashboard-required history access,
  dataset read, and other permissions defined by the existing source policy.
  Other roles retain their limited source-defined permission sets. Dataset
  visibility remains enforced by each role's dataset grants.
- Added regression coverage for stale role state, idempotency, limited role
  permissions, data preservation, dashboard empty state, and distinct frontend
  401/403/404/500 messages. Backend tests: 39 passed. Frontend tests: 17 passed.
  Frontend production build and Python compilation passed.
- Verified the running backend's registered summary endpoint over HTTP: no
  token returned 401; an active admin JWT returned 200 and the valid empty
  dashboard response. The active database has no registered datasets, so live
  chart activity and budget totals are empty/unavailable until datasets and
  releases exist. Browser rendering was not verified; manual browser checks
  remain pending.

## Adaptive policy and nominal accounting milestone — 2026-11-23

- Defined bounded risk components for sensitivity normalization, fixed data
  classification, dataset-wide history overlap, predicate/repetition proxy,
  and aggregate type. History is included once in the weighted risk score.
- Implemented deterministic allocation
  `clip(epsilon_max - 0.6 * risk - 0.3 * cumulative_utilization,
  epsilon_min, epsilon_max)`. An allocation above the remaining shared dataset
  budget is rejected without affordability clamping; the atomic reservation
  remains the race-safe final check.
- Cache lookup now binds selected epsilon along with dataset/version, query
  identity and values, authorization scope, mechanism, sensitivity, bounds,
  adjacency, and policy version. Exact cache reuse charges zero; a changed
  adaptive epsilon is a new nominally charged release. Release policy version
  changed to `protected-release-v3-adaptive-accounting`, making legacy cache
  entries ineligible for reuse.
- Query responses distinguish release calibration epsilon from
  `epsilon_charged`, and identify the accounting as `nominal_uncertified` with
  no established formal guarantee for the production finite-precision
  sampler. Budget endpoints validate accounting metadata and expose that
  status. The Risk Analysis page remains illustrative and now describes the
  backend history feature accurately.
- Added [adaptive_policy.md](docs/adaptive_policy.md) and updated mathematical,
  accounting, and API documentation. Existing database rows were not reset or
  reseeded; no credentials or database records were modified.
- Verification: backend tests 98 passed; frontend tests 19 passed; production
  build passed; `python -m compileall -q app tests` passed. No browser
  verification was performed in this milestone.

## Synthetic attack simulator and comparative experiments — 2026-11-23

- Added permission-protected `POST /api/attacks/simulate` and
  `POST /api/experiments/runs`, owner-scoped run listing/detail retrieval, and
  CSV export. Runs use generated in-memory employee data only; their persisted
  records contain summarized metrics and trial/request error measurements,
  not raw aggregate outputs or employee rows.
- Implemented four synthetic workloads: difference, repeated-query averaging,
  query narrowing, and overlapping-query inference. Added five comparisons:
  raw synthetic aggregate, uncapped fixed epsilon, budget-capped fixed
  epsilon, role-factor fixed epsilon with a shared simulated cap, and the
  existing history-aware adaptive policy with a shared simulated cap.
- Each baseline uses the same seeded synthetic dataset in a comparison. Exact
  cache repeats reuse one output at zero additional nominal charge. Repeated
  equivalent-identity variants and changed epsilon values create independently
  seeded outputs and nominal charges. Each trial resets its simulated cache
  and budget. The production noise sampler and production privacy ledger are
  not used or changed.
- Connected the existing Attack Simulator and Experiments pages to persisted
  backend runs, configuration controls, status/loading/error states, result
  comparisons, trial measurements, saved-run retrieval, and CSV export. The
  UI labels expenditure as nominal and uncertified; these synthetic results
  do not establish a formal DP guarantee.
- Documented methods and limits in [docs/attack_experiments.md](docs/attack_experiments.md)
  and added API documentation. Existing SQLite application data was not reset
  or reseeded; user credentials were not changed.
- Verification: backend suite 111 passed; frontend suite 21 passed; Vite
  production build passed; `python -m compileall -q app tests` passed. The
  experiment route and CSV persistence/export are covered by isolated SQLite
  route-level tests. A synchronous `TestClient`/ASGI request test hung during
  Windows AnyIO portal setup, before its assertion; this is a test transport
  limitation in this environment, so HTTP transport verification remains
  pending. API route registration and authorization/execution/persistence are
  verified directly in tests. No browser inspection was performed.
- Sample seeded synthetic run (difference workload, 5,000 rows, two trials,
  seed 2026, epsilon 0.5, budget 10): B0 reported attack success 1.0 and zero
  inference error (unprotected raw baseline); B1/B2 reported success 0.0,
  mean inference absolute error 643,133.32 and 4 releases / nominal epsilon
  2.0; B3 reported success 0.0, error 799,966.98 and nominal epsilon 1.75;
  B4 reported success 0.0, error 2,774,588.84 and nominal epsilon 0.609.
  These are one deterministic synthetic sample, not research conclusions,
  real-data findings, or formal privacy guarantees. Timing measures vary.

## Comparative research dashboard — 2026-11-25

- Added six versioned synthetic comparison models M0–M5, with M4 isolating exact caching from M5 adaptive allocation. Legacy B0–B4 request identifiers remain accepted; previously persisted rows are not rewritten.
- Added metrics for inference RMSE, cache hits/rate, answerability, budget-rejection counts, budget utilization, latency median/P95/SD and synthetic-engine component timings. Engine timing is explicitly not production SQL/API latency. The experiment route records definition versions, seed derivation and SQLAlchemy flush duration.
- Added an authenticated, permission-protected, owner-scoped `/api/experiments/benchmark-results` endpoint with scenario, dataset size, baseline, trial count, run and date filters/pagination. Added the Comparative Results navigation/page with persisted-run visualization, metric table, CSV export through the existing owner-authorized export, and a separate source-linked literature section.
- Added history-depth and M5-only experimental ablation configuration. The production adaptive policy formula and production noise sampler were not changed.
- Expanded Overview high-risk presentation with scored and unscored/rejected counts, threshold and percentage, and explicitly retained the heuristic/non-guarantee caveat.
- Literature entries are stored in `frontend/src/data/comparative-literature.json`. Only source-linked contextual findings are included; unlike metrics are not plotted together.
- Remaining gaps: no 500K campaign, production middleware concurrency benchmark, reliable peak-memory measurement, paired statistical significance testing, or multi-run compatibility comparison. Synchronous API experiment execution can be long at larger configurations. No formal end-to-end DP guarantee is established.

## Research metric integrity audit — 2026-11-26

- Added metric version v3 checks and explicit metric states so missing values remain distinct from measured zero. Relative error uses the absolute reference denominator and is unavailable below magnitude 1; UI percentages retain small nonzero values at two-decimal precision. Current binary attack-success intervals use Wilson; continuous mean intervals use Student-t for small samples and a normal-limit approximation after 30 observations.
- Added read-only per-run validation for trial/request arithmetic, success counts and thresholds, error summaries, relative-error aggregation, release/cache/nominal-epsilon reconciliation, metric ranges, confidence intervals and reproducibility metadata. API reports include run/scenario/dataset/baseline context and suggested actions. Historical records are evaluated on retrieval and are never rewritten.
- Corrected an integrity-check false positive: legacy aggregate RMSE was compared to pooled request RMSE even though older rows may record the mean of per-trial RMSEs. Unversioned run-level aggregation is now UNVERIFIABLE rather than FAIL. Cache consistency is now NOT_MEASURED when there were no cache hits; legacy default-true values without reuse are marked unverifiable.
- Read-only audit of existing Runs #1–#8 found no demonstrable arithmetic FAIL after the correction. All runs remain WARNING because historical definitions/evidence are incomplete, nominal accounting is uncertified, or scenario interpretation needs qualification. Run #7's M1/M2/M4 equality is explained by a nonbinding M2 cap and no M4 cache hits. Run #8's 20/20 success is full-dataset salary-SUM reconstruction within 5% tolerance, not individual-level inference; M4 records 80 cache hits and 20 independent releases, while M1/M2 record 100 releases.
- The documented audit is in `docs/RESEARCH_METRIC_INTEGRITY_AUDIT.md`. The SQLite database was accessed read-only; no historical result was modified, and no seeding or experiment execution was performed during the audit.
- Remaining research issue: the overlap scenario executes a North marginal aggregate that its current Engineering-minus-intersection inference formula does not use. Fixing this changes workload semantics and should be handled as a separately versioned experiment-protocol update. No formal end-to-end Differential Privacy guarantee is established.

## Research protocol v2 and experimental validity upgrade — 2026-11-26

- New synthetic runs persist a self-describing `privacyguard-research-protocol-v2` in the existing JSON run configuration, including scenario semantics, configured success tolerances, synthetic dataset generator/version, baseline settings, matched per-trial seeds, metric/statistical definitions and available execution environment. Historical runs are not retrofitted.
- Attack scenarios explicitly distinguish individual contribution inference (difference), population aggregate reconstruction (repeated), fixed scripted cohort-count narrowing, and aggregate intersection reconstruction (overlap). The v3 overlap workload uses Engineering SUM + North SUM − Engineering-or-North SUM, so every executed observation contributes to the declared estimator.
- Protocol v2 persists minimal owner-scoped synthetic target/inference evidence needed to validate attack error and success classification. It does not persist query aggregate outputs or employee rows. CSV export includes protocol and per-trial evidence under the existing run-owner permission check.
- Added within-run paired comparisons using matched stored trial seeds: exact McNemar for binary outcomes, paired sign-flip randomization tests for continuous outcomes, deterministic paired bootstrap intervals, paired Cohen's dz when defined, and Holm correction within each metric family. Samples below 20 complete pairs are exploratory. Cross-run compatibility can be checked in backend logic, but cross-run inference UI is not enabled.
- Added run quality-control states and surfaced protocol/QC/paired-analysis information in research results. Nominal epsilon remains uncertified; neither these analyses nor synthetic results establish formal end-to-end DP.
- Documentation: [docs/RESEARCH_PROTOCOL_V2.md](docs/RESEARCH_PROTOCOL_V2.md). No schema migration, database reset, reseed, historical modification, or project-database experiment execution was performed.
- Verification completed: backend `python -m pytest -q` — 130 passed; frontend `npm test` — 28 passed; `npm run build` — passed; `python -m compileall -q app tests` — passed. A focused M5 ablation regression test also passed after adding an epsilon-allocation assertion. Browser/live-system verification was not performed.

## Final research reproducibility and artifact audit — 2026-11-26

- Added a reproducibility checklist, observed environment/dependency manifest,
  Windows reproduction guide, current methodology guide, limitations document,
  and updated architecture/database/comparative-results/attack-experiment
  documentation.
- Corrected documentation drift: architecture and database docs now describe
  the implemented protected-query and isolated synthetic experiment paths;
  current comparison docs use Protocol V2, M0–M5, current metric/statistical
  versions, and clearly preserve legacy-run interpretation. README now
  identifies synthetic generation as implemented and PostgreSQL/CSV import as
  unestablished/pending.
- Environment observed: Python 3.11.9, Node 24.18.1, npm 11.12.1; frontend
  uses a lockfile, while backend requirements remain range-based without an
  exact Python lock. Git metadata was absent, so no commit ID/diff is available.
- Verification: with `DATABASE_URL=sqlite://`, backend `python -m pytest -q` —
  164 passed; `python -m compileall -q app tests` — passed; frontend `npm test`
  — 37 passed; `npm run build` — passed. No service, experiment, migration,
  seed command or project database operation was performed. Browser QA was not
  performed.
- Remaining artifacts before external submission: capture a source commit or
  archive checksum, create/review an exact Python lock if bit-for-bit setup is
  required, and have a researcher verify literature citations against source
  pages. The actual database/historical run contents were not rechecked in this
  documentation audit.

## Enterprise platform redesign — Stage 1 shell and information architecture — 2026-11-26

- Inspected the existing page IDs, route rendering, shell, live Overview API
  integration, visual tokens and responsive sidebar behavior before changing
  the navigation.
- Added `docs/ENTERPRISE_PLATFORM_ROADMAP.md`, mapping existing pages to the
  proposed enterprise groups and marking unimplemented connectors, tenancy,
  governance and monitoring modules as planned rather than adding dead links.
- Reorganized existing navigation groups without changing page IDs or route
  handlers. Applied a dark navy/slate sidebar with accessible active/hover
  states while retaining the current light content theme and existing Overview
  live-data/loading/error paths.
- Verification: frontend `npm test` — 38 passed; `npm run build` — passed.
  No backend behavior or API contract changed. No browser/desktop inspection,
  live service, database operation, experiment, seed or migration was run.
- Next gates: manual responsive shell QA, then a separately scoped connector
  design and isolated integration tests. PostgreSQL connection, tenant schema,
  and production readiness remain unimplemented/unverified.
