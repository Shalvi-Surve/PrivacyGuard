# Reproducibility environment and dependency manifest

## Environment captured for this audit

The following versions were observed in the current Windows workspace on
2026-11-26. They describe this machine's installed toolchain, not a guarantee
that another installation will resolve the same versions.

| Component | Observed version |
|---|---:|
| OS | Windows 11 workspace (PowerShell) |
| Python | 3.11.9 |
| Node.js | 24.18.1 |
| npm | 11.12.1 |
| FastAPI | 0.163.1 |
| Uvicorn | 0.50.2 |
| SQLAlchemy | 2.1.9 |
| SQLGlot | 29.0.1 |
| NumPy | 2.4.6 |
| SciPy | 1.17.1 |
| pandas | 2.3.3 |
| pytest | 8.4.2 |
| httpx | 0.28.1 |
| Alembic | 1.20.1 |
| PyJWT | 2.15.1 |
| pwdlib | 0.4.2 |
| pydantic-settings | 2.16.3 |
| React / React DOM | 19.3.1 / 19.3.1 |
| TypeScript | 5.9.3 |
| Vite | 6.4.6 |
| @vitejs/plugin-react | 4.7.0 |

The frontend versions above were read from `npm ls --depth=0`; the checked-in
`frontend/package-lock.json` is lockfile version 3 and should be used with
`npm ci` for repeatable installation. React and React DOM are now declared at
the exact versions recorded in the lockfile instead of using the moving
`latest` tag.

## Publication-preparation verification environment

On 2026-11-27, a new ignored `backend/.venv` was installed from
`backend/requirements.txt`; `pip check` passed. It resolved FastAPI 0.165.0,
Uvicorn 0.54.0, Pydantic 2.14.4, pydantic-settings 2.16.3, SQLAlchemy 2.1.9,
SQLGlot 29.0.1, PyJWT 2.15.1, pwdlib 0.4.2, NumPy 2.4.6, pandas 3.1.1,
SciPy 1.17.1, httpx 0.29.0, and pytest 8.4.2. The backend requirements file
still uses compatible ranges rather than exact pins, so this is a verification
snapshot, not a lockfile.

## Dependency declarations and pinning

- Backend declarations are in `backend/requirements.txt`. They use broad
  compatible version ranges (for example, `fastapi>=0.115,<1`) and are **not**
  an exact lock. The captured versions above are an environment snapshot only.
- No Python lockfile or checked-in exact `pip freeze` is present. A fresh
  `pip install -r requirements.txt` can resolve newer compatible releases.
- Frontend dependency resolutions are pinned by `frontend/package-lock.json`.
  Use `npm ci`, not `npm install`, for reproduction from the lock.
- Git metadata was absent during the original 2026-11-26 audit. The repository
  is now initialized; capture `git rev-parse HEAD` with future experiment
  artifacts. Historical runs still do not contain a source commit binding.

## Configuration

`.env.example` documents the local settings:

| Variable | Default / purpose |
|---|---|
| `APP_ENV` | `development` |
| `DATABASE_URL` | `sqlite:///./adaptive_dp.db` relative to backend working directory |
| `JWT_SECRET_KEY` | Development placeholder; replace locally, never publish it |
| `JWT_ACCESS_TOKEN_MINUTES` | `30` |
| `VITE_API_BASE_URL` | Empty means same-origin; development Vite proxy targets `127.0.0.1:8000` |
| `VITE_API_PROXY_TARGET` | Optional development proxy target override |
| `CORS_ALLOWED_ORIGINS` | Empty by default; configure exact origins only for separate frontend hosting |

Outside development, the settings validator rejects a missing/template/short
JWT key and the default SQLite database URL. Production schema migration and
PostgreSQL deployment remain unverified.

Never put secrets in a `VITE_` variable: Vite embeds such variables in client
assets. Do not commit `.env` or research database files. The experiment
campaign runner accepts only loopback API origins and holds credentials and
bearer tokens in memory.

## Recreate the captured frontend toolchain

```powershell
cd D:\info-sec\differential-privacy-proxy\frontend
npm ci
npm ls --depth=0
```

For Python, install into a fresh project-local virtual environment as shown in
[`EXPERIMENT_REPRODUCTION.md`](EXPERIMENT_REPRODUCTION.md). For exact package
reproduction across machines, create and review a Python lock file in a
separate dependency-management change; this audit does not silently convert
the project's requirements ranges into pins.
