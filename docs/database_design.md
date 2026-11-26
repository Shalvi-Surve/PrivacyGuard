# Database and persistence design

## Storage roles

The development application defaults to SQLite at
`backend/adaptive_dp.db` when started with `backend` as the working directory.
`DATABASE_URL` can select another SQLAlchemy URL. The current project workflow
uses SQLite; PostgreSQL deployment, migration behavior and concurrency
characteristics are not established by this prototype. The installed Alembic
dependency is not evidence that production migrations are ready.

SQLAlchemy models include identity/RBAC tables, dataset registry and grants,
privacy budget and ledger, protected release cache, query history, audit logs,
and experiment run/result records. See `backend/app/database/models.py` for
the actual schema; do not treat this summary as a migration specification.

## Protected-query accounting persistence

The shared authoritative budget scope is one row per dataset with
`scope=dataset` and no user owner. Users authorized for the same dataset share
that scope. Reservation uses a conditional SQL update against remaining
balance. A new release, budget ledger charge, request history and audit event
are committed in the caller's transaction after the protected result is
prepared. A failure rolls back the reservation/release writes. An exact
compatible cache hit returns the stored release without another ledger charge.
The ledger is labeled `nominal_uncertified`; it does not certify the mechanism
or an end-to-end DP guarantee. See `privacy_accounting.md`.

## Synthetic experiment persistence

`experiment_runs` stores owner, status, seed, timestamp and JSON configuration
(including the versioned protocol for new runs). `experiment_results` stores
per-baseline metric JSON, including per-trial and request measurements and
minimal synthetic target/inference evidence. Run data retrieval and CSV export
are owner-scoped and permission protected. Raw synthetic employee records and
aggregate outputs are not persisted by the experiment engine. The read-only
integrity report is derived from these stored fields; historical data is not
retroactively changed.

The API's create-all/schema initialization behavior is a development
convenience, not a reviewed migration path. No migration or database operation
was performed for the reproducibility documentation audit. Tests should use
temporary or in-memory SQLite fixtures and must never point at the project
research database. See `EXPERIMENT_REPRODUCTION.md` for safe commands.
