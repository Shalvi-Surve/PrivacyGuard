# Deployment and publication status

PrivacyGuard is a research prototype. The container files provide a repeatable
build and reverse-proxy layout; they are not evidence of production readiness.

## Current deployment blockers

1. No complete Alembic environment/revision chain is configured. The backend
   creates and applies local schema changes only when `APP_ENV=development`.
   Production startup does not bootstrap tables. Do not expose a deployment
   until a non-destructive, reviewable migration has been implemented and
   tested against a disposable copy of the target database.
2. SQLite is the tested development database. PostgreSQL dependencies exist,
   but PostgreSQL behavior, migration and operational characteristics have not
   been verified.
3. There is no production secret-management, TLS, backup/recovery, monitoring,
   rate-limiting, or incident-response configuration in the repository.
4. No tenant-isolation or production security certification is claimed.

## Container topology

- `backend/Dockerfile` runs Uvicorn as a non-root user on container port 8000.
- `frontend/Dockerfile` builds the locked frontend dependency tree and serves
  static assets through Nginx.
- `frontend/nginx.conf` sends `/api` and `/health` to the internal backend
  service; the backend is not mapped to a public host port in Compose.
- `docker-compose.yml` binds the frontend to `127.0.0.1:8080` by default.
  A public platform must provide its own ingress and TLS termination.

The backend requires `APP_ENV=production`, `DATABASE_URL`, and a unique
`JWT_SECRET_KEY` (minimum 32 characters; development/template keys are
rejected). `CORS_ALLOWED_ORIGINS` should remain empty for the same-origin
reverse-proxy topology; otherwise use exact approved origins. Never put secret
values in the frontend build environment.

Compose reads an untracked `.env` at the repository root for interpolation.
Do not copy the local SQLite URL or development JWT placeholder from
`.env.example` into a deployment. Supply a schema-ready, disposable database
for container smoke tests; never use the historical research database.

## Example build/run after migration work is complete

From a shell with deployment-only `DATABASE_URL` and `JWT_SECRET_KEY` set:

```sh
docker compose config
docker compose build
docker compose up -d
```

The project must first provide and apply an approved migration using a
separate operational procedure. No migration command is currently available;
the example above is therefore not a go-live procedure. After startup, verify
health/readiness, login, RBAC, owner-scoped records, CORS/ingress behavior,
logs, backups, and recovery using non-production accounts and data.

## Local development

Use the PowerShell commands in the repository README. Local development mode
can create the application schema and apply additive SQLite changes. This
behavior must not be used against production or historical research data.

## Publication exclusions

`.gitignore` excludes local databases, database journals, logs, reports,
backups, temporary research files, environment files, dependency directories,
and generated bundles. Review the staged files before every publication; an
ignore file does not remove an artifact that was already tracked elsewhere.
