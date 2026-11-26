# API documentation

FastAPI OpenAPI documentation is served at `/docs` when the API runs.

## Implemented endpoints

- `GET /health` — process liveness and a `database.status` probe (`available`
  or `unavailable`) with overall `readiness` (`ready` or `degraded`). The
  process-health status stays `ok` when the database is down; database-backed
  routes such as login may still fail.
- `POST /api/auth/login` — username/password login; returns a bearer JWT.
- `POST /api/auth/logout` — stateless client logout placeholder; clients discard
  their token. Server-side revocation is not implemented.
- `GET /api/auth/me` — returns the authenticated user's profile and role names.
- `POST /api/queries/analyze` — requires `queries:submit`, validates the
  restricted SQL subset, and returns structural metadata. It does not execute
  SQL or release an aggregate.
- `POST /api/queries/execute` — requires `queries:execute_protected` and an
  authorized dataset grant. It returns the protected aggregate, selected
  nominal `epsilon`, actual `epsilon_charged` for this request (zero on cache
  reuse), bounded heuristic risk components, and an auditable allocation
  decision. `accounting_status` is `nominal_uncertified` and
  `privacy_guarantee_status` reports that a formal guarantee for the
  finite-precision sampler is not established. The shared dataset budget
  rejects an unaffordable new allocation; cache reuse requires an exact match
  including epsilon.
- `GET /api/dashboard/summary?days=7` — requires a bearer JWT and
  `history:read_own` or `history:read_all`. Returns permission-scoped persisted
  metrics, per-decision activity for 1–90 days, recent query metadata, shared
  dataset budget health, safe audit descriptions, and operational signals.
  `history:read_own` users see only their own query records; `history:read_all`
  users see records for datasets their roles can read. Dataset counts and
  budget rows are limited to role-granted datasets. Audit descriptions expose
  no stored metadata; only users with `audit:read` see system-wide events.
  Request totals include each submitted analysis/protected request, including
  a cached-repeat request. `protected_releases` counts unique stored releases
  (and for own-history users, unique protected query identities visible in
  their own history). Analysis-only decisions are counted as approved requests;
  budget/validation rejections are rejected; other recorded states are shown
  separately. Missing budget rows return null totals rather than estimates.
- `GET /api/budgets` — requires `budgets:read_own` or `budgets:read_all` and
  returns the shared dataset budget and ledger for role-granted datasets.
  Totals are nominal epsilon accounting and responses mark this as
  `nominal_uncertified`.
- `GET /api/queries/history` — requires `history:read_own` or
  `history:read_all` and returns paginated request metadata.
- `GET /api/audit` — requires `audit:read` and returns paginated audit records.
- `POST /api/attacks/simulate` — requires `experiments:run`; runs a selected
  inference scenario against fresh seeded synthetic employee data and saves
  metrics for the selected baselines. It does not use registered datasets.
- `POST /api/experiments/runs` — requires `experiments:run`; runs a comparative
  synthetic workload and persists per-baseline summary, per-trial, and
  request-level measurements. Run options are bounded to 5,000, 25,000, or
  100,000 generated rows; 1–30 trials; and 2–20 repeated requests.
- `GET /api/experiments/runs` and `GET /api/experiments/runs/{id}` — require
  `experiments:run`; list or retrieve only the authenticated user's runs.
- `GET /api/experiments/runs/{id}/export.csv` — requires `experiments:run` and
  exports saved measurement rows without raw aggregates or synthetic records.

Attack and experiment endpoints use synthetic-only workloads. Their reported
epsilon is nominal; the current production sampler and adaptive pipeline have
no established formal end-to-end DP guarantee. The login response does not
include database credentials. Passwords are hashed with the configured
`pwdlib` recommended password hasher.
