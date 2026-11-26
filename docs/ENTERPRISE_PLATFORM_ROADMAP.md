# Enterprise platform upgrade roadmap

This staged roadmap maps existing PrivacyGuard capabilities into the proposed
enterprise information architecture. It does not claim unimplemented pages,
connectors, tenancy or operational controls are available. Each stage must keep
existing route IDs, API contracts and historical research data compatible.

## Current implementation status (2026-11-26)

- Stage 0: source/page/API documentation inventory completed; the workspace has
  no Git metadata, so commit/diff baseline is unavailable. No database operation
  was performed.
- Stage 1: existing page grouping and dark navy shell foundation implemented;
  existing routes and live Overview data path preserved. Automated frontend
  tests and production build pass. Manual browser/responsive QA remains pending.
- Stages 2–7: planned; no connector, tenant model, additional governance page,
  or monitoring capability is claimed by this first implementation slice.

## Existing-page mapping

| Proposed group | Existing page(s) mapped now | Not yet represented by a working page |
|---|---|---|
| Overview | Overview | System Health; Alerts & Notifications |
| Data & Connectivity | Dataset Management | Data Sources; Connector Management; Schema Explorer; Connection Health |
| Query Workspace | Query Console; Query History | Saved Queries; Query Results; Query Policies as separate modules |
| Privacy Management | Privacy Budgets | Privacy Accounting; Adaptive Allocation; Privacy Cache; Release Ledger; Budget Policies as separate modules |
| Security & Governance | Risk Analysis; Attack Simulator; Audit Logs; User & Role Management | Threat Assessment; Tenant Management; Security Posture |
| Research & Evaluation | Experiments & Evaluation; Comparative Results | Protocol registry; separate Statistical Analysis, Attack Evaluation and Research Reports modules |
| Operations | System Architecture | Service/Concurrency/Job monitoring; Backups & Recovery; deployment configuration |
| Administration | Settings; User & Role Management | Organizations; Workspaces; API access administration |

The first UI stage groups existing pages only. It does not add dead-end
navigation for the unimplemented items above. Settings and user management are
retained, with users grouped under Security & Governance in the current shell;
the table records that they also serve administrative duties.

## Stages and acceptance gates

### Stage 0 — inventory and preservation baseline

- Map existing page IDs, authenticated APIs, database ownership scopes and
  documented limitations.
- Record test/build baseline and ensure work does not use the project database.
- Gate: all existing page routes remain reachable; no historical data action.

### Stage 1 — design foundation, shell and live Overview

- Establish shared enterprise color/type/spacing tokens while keeping the
  current light content canvas and introducing the requested dark navy shell.
- Reorganize navigation labels/groups around existing pages only.
- Preserve collapsed/mobile navigation, global page search, workspace context,
  authentication, API status/error behavior and live Overview data.
- Gate: frontend tests/build; no fake operational metrics; responsive checks
  and manual browser review remain required before release.

### Stage 2 — connector and data-source boundary

- Specify connector interface and credential/configuration threat model before
  any external connection code.
- Keep SQLite and registered synthetic datasets operational. Add PostgreSQL
  support only in an isolated branch with read-only credentials, query
  timeouts, schema allowlisting and explicit operator configuration.
- Gate: connector contract tests and isolated DB integration tests; no automatic
  connection or production credential handling.

### Stage 3 — accounting, cache and concurrency evidence

- Complete protected-release identity/canonicalization review, transactional
  accounting invariants, failure semantics and race tests.
- Preserve the locked M5 parameters and historical records.
- Gate: isolated concurrency and rollback tests; no formal DP claim until the
  sampler and adaptive composition are independently proved.

### Stage 4 — tenant-aware domain and migration design

- Model organizations/workspaces and define tenant ownership for every
  relevant record and cache/accounting scope.
- Prepare additive migration and isolated migration test before any live DB
  application.
- Gate: cross-tenant authorization/cache/accounting isolation tests, backup and
  explicit review before application to a real database.

### Stage 5 — governance workflows

- Build evidence-backed threat/control registry and assessment workflow.
- Derive status from tests/evidence; do not create an unsupported security
  score.
- Gate: RBAC coverage, audit safety and documented residual risk.

### Stage 6 — research workbench

- Improve existing experiments/results with versioned protocol, QC,
  reproducibility evidence, comparisons and exports while preserving ownership
  and persisted historical definitions.
- Gate: no fabricated data; matched comparisons only; limitations and
  statistical eligibility visible.

### Stage 7 — operations and deployment readiness

- Add operational metrics only where actual backend instrumentation exists.
- Document backups/recovery, secrets, TLS, database roles and process health.
- Gate: operational checks and deployment threat review; no readiness label
  without corresponding verification evidence.

## Non-negotiable safeguards

- Do not reset, seed, migrate or overwrite the research database as part of UI
  work.
- Do not alter users, credentials, privacy policy parameters or historical
  experiments without a specifically scoped authorization.
- Keep synthetic experiment execution separate from the production query path.
- Mark capabilities as planned, simulated, implemented, tested or verified
  based on evidence; do not conflate those states.
- Keep the finite-precision production sampler, heuristic M5 policy and
  nominal accounting limitations explicit.
