# Implementation roadmap

## Milestone 1 — Environment and skeleton

- [x] Inspect repository, Git state, installed runtime versions, and provided references.
- [x] Create backend/frontend starter structure and configuration examples.
- [x] Document target architecture and staged delivery.
- [x] Install Python and npm dependencies.
- [x] Verify frontend production build, backend import/compile, backend startup, and same-origin API communication through the Vite proxy.
- [x] Check PostgreSQL availability; no client or local server was found/reachable.

## Milestone 2 — Database and authentication

- [x] Initial SQLAlchemy schema for users, roles, permissions, dataset budgets, history, audit, and experiments.
- [ ] Alembic migrations and synthetic enterprise dataset generator.
- [x] Password hashing, JWT login/logout/profile, active account checks.
- [x] Permission lookup dependency and demonstration role/user seed script.
- [ ] Complete table/column/aggregate permission matrix and admin user management.

## Milestone 3 — Query middleware

- [x] SQLGlot parser, restricted COUNT/SUM SELECT validation, normalization and structural fingerprints.
- [ ] Allowlisted, parameterized aggregate execution using a read-only DB identity.

## Milestone 4 — Fixed Differential Privacy

- [x] Standalone Laplace mechanism and COUNT / bounded-SUM sensitivity helpers.
- [ ] Integrate mechanism with clipped PostgreSQL aggregate execution and release responses.
- [ ] Document adjacency and sensitivity assumptions; defer unsupported AVG.

## Milestone 5 — Privacy accounting

- [x] Atomic conditional shared-dataset charge, sequential composition ledger, and exhaustion rejection (PostgreSQL concurrency still unverified).
- [ ] Per-user attribution, role scope, threshold configuration, and concurrency validation against PostgreSQL.
- [ ] Exhaustion enforcement and release cache semantics.

## Milestone 6 — Query history

- [ ] Similarity, repetitions, narrowing and correlation indicators with evidence.

## Milestone 7 — Adaptive privacy

- [x] Standalone explainable weighted risk and clipped epsilon-policy helpers.
- [ ] Connect query history, cumulative spend, policy configuration, and release decisions.
- [ ] Clearly distinguish heuristic allocation from formal DP accounting.

## Milestone 8 — Research evaluation

- [ ] Four attack workloads, five baselines, metrics, ablations, exports and plots.
- [ ] Use actual runs and preserve seeds/configuration; do not prestate outcomes.

## Milestone 9 — Frontend completion

- [ ] API-backed dashboard, query console, history, privacy, attack, experiment,
  administration and audit experiences.

## Milestone 10 — Validation and documentation

- [ ] Automated security, privacy, API, frontend and end-to-end validation.
- [ ] Update documentation to match actual implemented behavior and limitations.

## Next concrete action

Implement Milestone 2 using synthetic data only. PostgreSQL installation and
configuration is the main environment dependency to resolve before live database
integration; work on database models and authentication can proceed in parallel.
