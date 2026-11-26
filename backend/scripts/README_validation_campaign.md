# Running the locked validation campaign (Windows)

Start the current PrivacyGuard backend from this checkout, then open PowerShell
in the project directory and run:

```powershell
cd D:\info-sec\differential-privacy-proxy\backend
py -3 .\scripts\run_validation_campaign.py
```

The runner defaults to `http://127.0.0.1:8000`; enter another locally configured
backend URL only if needed. It asks for the Researcher username and uses
`getpass` for a non-echoing password prompt. The password and bearer token are
held only in process memory. The script verifies `/api/auth/me` and makes an
owner-scoped `GET /api/experiments/runs` request to confirm effective
`experiments:run` permission before it displays the locked configuration.
For credential safety, the configured URL is restricted to a local loopback
origin (localhost, 127.0.0.1, or ::1).

Execution requires typing this exact phrase at the local terminal prompt:

```text
RUN PRIVACYGUARD VALIDATION
```

The locked settings are embedded in the script to avoid accidental drift: four
scenarios; 5,000 synthetic employee rows; base seed 20261126; 20 matched hashed
trial seeds; M0–M5; fixed epsilon 0.5; per-trial nominal budget 5.0; M5
`adaptive_risk_penalty=0.10` and `adaptive_cumulative_penalty=0.05`; and the
predeclared scenario tolerances and protocol settings. The runner submits one
authenticated `POST /api/experiments/runs` per scenario and verifies each
owner-scoped persisted run. It does not read the project SQLite file, seed,
migrate, reset, or delete data.

Completed matching runs are reused rather than submitted again. A matching
non-completed run blocks another submission. If a POST times out or the process
is interrupted, the runner checks owner-scoped run records, writes a status
report, and never retries an uncertain submission automatically. Review the
persisted status before taking further action.

Reports are written without credentials or tokens to a unique Markdown file in
`backend\reports\`. The report includes run IDs, per-baseline trial coverage,
attack/error/accounting/cache/adaptive metrics when returned, integrity and
quality status, paired-comparison availability, and limitations. Nominal
epsilon is explicitly uncertified; this campaign does not establish a formal
end-to-end differential privacy guarantee. The report directory contains
research results, so keep it within the project's existing access controls.

Tests use mocked HTTP and synthetic response objects only. They do not submit a
campaign, access real credentials, or mutate the application database.
