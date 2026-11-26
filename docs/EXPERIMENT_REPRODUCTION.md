# Reproducing PrivacyGuard synthetic experiments

This guide describes how to reproduce a new synthetic run. It does not claim
that this audit executed an experiment. Do not use an existing research
database for a trial run unless the operator explicitly intends to add a
permanent record. Prefer a disposable SQLite database for a reproduction.

## 1. Recreate the software environment

From PowerShell:

```powershell
cd D:\info-sec\differential-privacy-proxy\backend
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cd ..\frontend
npm ci
```

Python requirements use version ranges, so this is not bit-for-bit dependency
reproduction. The current observed tool versions and pinning limitations are
recorded in [`reproducibility_manifest.md`](reproducibility_manifest.md).

## 2. Use an isolated development database

Copy `.env.example` to `.env` only for a local disposable environment. Set a
new local `JWT_SECRET_KEY`, and set `DATABASE_URL` to a new SQLite file. The
relative SQLite path is resolved from the backend process working directory.
Do not copy the project's existing `backend/adaptive_dp.db` into a test target
or run a seed command against the research database.

Start the services in separate PowerShell windows:

```powershell
cd D:\info-sec\differential-privacy-proxy\backend
..\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```powershell
cd D:\info-sec\differential-privacy-proxy\frontend
npm run dev
```

Use the local application to sign in with an authorized account and create a
run through Research → Experiments & Evaluation. The run API is
`POST /api/experiments/runs`; it requires the existing `experiments:run`
permission. The run list/detail, paired comparison and CSV APIs are
owner-scoped. Do not put credentials or bearer tokens in a saved script or
report.

## 3. Reproduce a single controlled run

Record the exact submitted configuration with the run. For controlled
baseline comparisons, select all applicable M0–M5 baselines in one run, choose
one of the supported scenarios (`difference`, `repeated`, `narrowing`,
`overlapping`), use the same dataset size, seed, trial count, epsilon, budget,
success thresholds, trial-seed strategy, history depth and ablation settings.
The API accepts dataset sizes 5,000, 25,000 or 100,000 rows and 1–30 trials;
the standalone generator supports 500,000, but that size is not accepted by
the experiment API. Start with a small trial count and 5,000 rows. Do not
increase scale without considering synchronous request time and available
memory.

For an exact run identity, retain its persisted Protocol V2 object. Dataset
generation uses Python's seeded `random.Random` and `synthetic-employee-
generator-v1`. Protocol V2 stores the dataset seed, derived trial seeds,
generator/workload/attack/mechanism/metric versions, policy settings, success
criteria, and available Python/platform information. Timing values are
expected to vary across machines and runs even when data/noise seeds match.

## 4. Retrieve and review

After an authorized run, review it through:

- `GET /api/experiments/runs` — owner-scoped run list.
- `GET /api/experiments/runs/{id}` — persisted configuration, results,
  protocol, integrity validation, quality state and paired comparisons.
- `GET /api/experiments/runs/{id}/paired-comparisons` — paired analysis.
- `GET /api/experiments/runs/{id}/export.csv` — owner-authorized trial/request
  measurements and protocol evidence.
- `GET /api/experiments/benchmark-results` — owner-scoped completed runs for
  Comparative Results.

Review integrity findings and quality status before interpreting numbers.
An `UNVERIFIABLE` finding means the persisted evidence is insufficient; it is
not a pass. Runs below 20 complete matched pairs are exploratory. Even at 20
pairs, statistical methods and their assumptions must be considered; a p-value
does not prove generalization or practical importance.

## 5. Locked validation runner (operator-initiated only)

The terminal-only runner embeds the locked campaign to reduce configuration
drift. It prompts locally for a username and hidden password, verifies the
active Researcher identity and `experiments:run`, prints the campaign settings,
and submits only after the exact local confirmation phrase. It never reads the
database file or stores credentials/tokens. This audit did not execute it.

```powershell
cd D:\info-sec\differential-privacy-proxy\backend
..\.venv\Scripts\Activate.ps1
python .\scripts\run_validation_campaign.py
```

The runner may create permanent experiment records and report files. Use it
only when the campaign is authorized and the intended backend/database have
been positively verified. Its settings and safety behavior are documented in
[`../backend/scripts/README_validation_campaign.md`](../backend/scripts/README_validation_campaign.md).

## 6. Automated verification (no research campaign)

From the backend directory, force the test process to an in-memory SQLite URL
before collection. Test fixtures also create isolated temporary SQLite files.
The environment override prevents accidental use of a developer's configured
database URL:

```powershell
cd D:\info-sec\differential-privacy-proxy\backend
$env:DATABASE_URL = 'sqlite://'
python -m pytest -q
python -m compileall -q app tests
Remove-Item Env:DATABASE_URL
```

From the frontend directory:

```powershell
cd D:\info-sec\differential-privacy-proxy\frontend
npm test
npm run build
```

Automated unit/route tests may invoke the synthetic engine on small in-memory
fixtures. They do not constitute campaign results and must not be described as
new research measurements.
