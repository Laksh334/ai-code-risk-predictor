# AI-Powered Code Complexity & Technical Debt Predictor

Analyzes a GitHub repository, predicts which files are likely to become bug-prone or
expensive to maintain in the next 3–6 months, explains **why** (SHAP), and ranks every file
as **Critical / High / Medium / Low** risk, so engineering managers know what to fix first.

## How the pieces fit

```
GitHub repo ──► pipeline/ (Member 1) ──► features CSV ──► ml/ (Member 2) ──► predict(file_data)
  git history + AST/Radon/Lizard metrics           XGBoost/RF + commit-message NLP + SHAP
                                                                         │
React dashboard ◄── REST API ◄── backend/ (Member 3) ◄───────────────────┘
frontend/ (Member 4)             FastAPI + PostgreSQL + GitHub webhooks (PR comments)
heatmap, trends, SHAP charts
```

| Folder | Role | Stack |
|---|---|---|
| `pipeline/` | Member 1 — Data extraction & processing | Python, GitPython, `ast`, Radon, Lizard, pandas |
| `ml/` | Member 2 — Prediction, NLP, explainability | scikit-learn, XGBoost, HuggingFace, SHAP |
| `backend/` | Member 3 — APIs, database, GitHub App | FastAPI, SQLAlchemy, PostgreSQL, Docker |
| `frontend/` | Member 4 — Dashboard & data viz | React, Tailwind, Recharts/D3, Zustand |

## Setup (Python parts)

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r pipeline/requirements.txt -r backend/requirements.txt
```

## Data pipeline usage (Member 1)

**Main entry point (A4)** — everything below is wrapped by one command:

```powershell
python -m pipeline.run scan https://github.com/psf/requests   # features of today's code (for predictions)
python -m pipeline.run dataset                                # training set from pipeline/repos.txt
python -m pipeline.run refresh                                # pull all repos, update features + dataset
python -m pipeline.run refresh --every 360                    # keep feeding fresh data every 6 hours
```

- `pipeline/repos.txt` lists the training repos (requests, flask, click, httpx today: 3,051 rows,
  95 snapshots, 14% bug-prone). Add a line to add a repo.
- Commits are cached in `data/cache/` and only **new** commits are parsed on each refresh
  (falls back to a full re-parse after a force-push); static metrics of past snapshots are
  cached by commit. A full first run takes ~4–5 min, a refresh ~40 s.
- If GitHub is unreachable, the local copy is used and the run continues.
- In code (used by the backend in C1): `from pipeline.scanner import scan_repository` →
  `result.features` has exactly the training feature columns (`dataset.META_COLS` /
  `dataset.LABEL_COLS` list the non-feature columns).

Individual steps:

```powershell
# A1 - Git history: commits table + per-file history features
python -m pipeline.git_history https://github.com/psf/requests
python -m pipeline.git_history data/repos/psf__requests --until 2016-01-01

# A2 - Static analysis of every Python file (today, or at any past commit/date)
python -m pipeline.static_analysis data/repos/psf__requests
python -m pipeline.static_analysis data/repos/psf__requests --rev 2016-01-01

# A3 - Training dataset: snapshot every 6 months, label = bug fixes in the next 6 months
python -m pipeline.dataset data/repos/psf__requests
python -m pipeline.dataset https://github.com/psf/requests https://github.com/pallets/flask --interval 3
```

**How the A3 dataset avoids cheating:** at each snapshot date T, features use only commits
*before* T and the code *as it was* at T; labels count only what happens *after* T
(`future_bug_fixes`, `future_commits`, `future_churn`, `label_bug_prone` = at least one bug fix).
Snapshots whose label window isn't over yet are dropped. File renames are followed, so a
2013 `requests/models.py` row joins the history of today's `src/requests/models.py`.
Bug-fix commits are detected from commit messages; "fixes" about docs/typos/CI/lint, and fix
commits touching more than 10 files (bulk changes), don't count.

Example (`psf/requests`): 548 rows, 28 snapshots (2012–2025), 21% bug-prone. Bug-prone files
have higher recent activity, complexity, size and coupling, and lower maintainability.

Outputs go to `data/processed/` (git-ignored). Vendored third-party folders
(`vendor/`, `third_party/`, `pkg/packages/`, …) are skipped by both steps (`pipeline/filters.py`).

| Step | Per-file columns |
|---|---|
| A1 history | `commit_count`, `churn`, `lines_added/deleted`, `num_developers`, `top_author_share`, `bug_fix_count`, `bug_fix_ratio`, `recent_commit_count`, `recent_churn`, `age_days`, `days_since_last_change` |
| A2 static | `loc`, `sloc`, `comment_ratio`, `num_functions`, `num_classes`, `avg/max/total_complexity`, `avg/max_function_length`, `max_params`, `max_nesting_depth`, `maintainability`, `halstead_volume`, `num_imports`, `fan_in`, `fan_out`, `coupling`, `instability`, `duplication` (%), `is_test_file`, `has_test_file`, `test_importers`, `parse_ok` |

## Commit-message NLP (Member 2, B1 — `ml/nlp.py`)

```powershell
pip install -r ml/requirements.txt   # CPU PyTorch + Transformers (~200 MB, + ~330 MB model on first run)
```

Each commit gets `msg_*` signals; per file they are averaged over its history before the
snapshot date (e.g. `msg_frustrated` = share of the file's commits that sound frustrated):

| Signal | How | Predictive value on 3,051 rows (AUC overall / at equal activity, 0.5 = none) |
|---|---|---|
| `msg_hf_frustration` | HuggingFace `j-hartmann/emotion-english-distilroberta-base`: P(anger)+P(disgust), cached per commit | **0.68 / 0.62** — best NLP signal |
| `msg_words` | message length | 0.62 / 0.61 |
| `msg_rushed` | lexicon: wip, quick fix, hack, workaround, for now, forgot… | 0.65 / 0.55 |
| `msg_frustrated` | lexicon: stupid, again, finally, wtf, ugh, "!!"… | 0.62 / 0.54 |
| `msg_short` | ≤ 3 words | 0.47 / 0.40 — *inverse*: files with terse commits were *less* bug-prone |
| `msg_revert`, `msg_late_night`, `msg_weekend` | revert commits; local time 22:00–06:00; Sat/Sun | ≈ 0.5 — no signal here |

For comparison: `loc` 0.79, `max_complexity` 0.75, `recent_commit_count` 0.70. Known limitation:
the emotion model was trained on everyday English, so programming words like "kill", "dead",
"useless" read as anger. Its per-file averages still carry signal. All signals stay as features;
B2's model decides how much to trust each one.

## Model training & results (Member 2, B2 — `ml/train.py`)

```powershell
python -m ml.train          # ~3 min: tunes, compares, saves data/models/risk_model.joblib + report.json
```

**Fair evaluation:** test = snapshots from 2023 on (764 rows, 76 bug-prone), never used for
training or tuning. Training uses only snapshots whose 6-month label window ends before 2023
(2,168 rows). Hyper-parameters are tuned with expanding-window validation (2019–2022). The model
is picked by validation score, not by test score.

| Test set (2023+) | ROC-AUC (95% CI) | PR-AUC | Bug-prone files caught in top 20% | Precision of top 5 | Train ROC-AUC |
|---|---|---|---|---|---|
| Random order | 0.50 | 0.11 | 21% | 0.13 | – |
| Baseline: biggest files first | 0.81 (0.77–0.85) | 0.33 | 63% | 0.36 | – |
| Baseline: most recently active | 0.63 (0.58–0.70) | 0.18 | 50% | 0.33 | – |
| **Logistic regression (selected)** | 0.80 (0.77–0.83) | 0.31 | 63% | 0.38 | 0.85 |
| Random forest | 0.81 (0.78–0.85) | 0.27 | 64% | 0.37 | 0.93 |
| XGBoost | 0.74 (0.70–0.77) | 0.21 | 44% | 0.25 | **0.98 → overfits** |
| Ensemble (logistic + RF) | 0.81 (0.78–0.84) | 0.28 | 65% | 0.38 | 0.89 |

Unseen repository (train on 3, test on the 4th): ROC-AUC 0.79–0.86, so it works on repos it never saw.

**Honest findings**
- The models are ~3× better than random at picking the top 5 risky files, but statistically
  **tied with "biggest files first"** — a well-known effect in defect-prediction research.
- Dropping all 13 size features gives the *same* accuracy (0.80): complexity, coupling, history
  and NLP signals carry the information too.
- XGBoost memorised the training years (train 0.98 vs test 0.74) — rejected.
- **Effort-aware limitation:** after reading 20% of the *lines of code*, every method (including
  risk-per-line ranking) finds only ~8–17% of future bug-prone files, about the same as random. More
  repositories / finer labels are the next lever.
- Logistic regression was selected: tied for best, simplest, least overfit, and easy to explain.

## Explanations & recommendations (Member 2, B3 — `ml/explain.py`)

```python
from ml.explain import RiskExplainer
explainer = RiskExplainer.from_bundle(joblib.load("data/models/risk_model.joblib"))
explainer.explain(features_df)  # per file: risk_score, explanation, factors, recommendation
```

- **SHAP values** per file and feature (`LinearExplainer` for the logistic model; tree and
  model-agnostic explainers are supported too). Verified exact: base value + sum of SHAP values =
  the model's score (error ~1e-15).
- **Factors:** related features are summed into Size, Complexity, Change activity, Bug history,
  Team, Coupling, Tests, Duplication, Commit messages. SHAP values are additive, so this is exact,
  and it hides confusing sign splits between overlapping features (e.g. size vs maintainability).
- **Recommendations** come from the factors that raise risk most, filled with the file's own numbers,
  and only when they make sense (e.g. "split this file" needs ≥ 400 lines). Files below 0.35 risk
  get "no action needed".

Example — `psf/requests` `src/requests/models.py` (risk 0.89): Size +0.98, Coupling +0.71,
Bug history +0.45 (152 past fixes), Team +0.26; its age pulls risk down (−0.56). Advice: *"Split this
1,184-line file into smaller, focused modules. Highly connected (imported by 10 files, imports 12):
hide it behind a smaller interface so changes don't ripple."*

What drives risk overall (mean |SHAP| on the 2023+ test set): Size 0.50 · Change activity 0.46 ·
Coupling 0.29 · Tests 0.19 (having tests lowers risk) · Bug history 0.12 · Complexity 0.12 ·
Commit messages 0.10 · Team 0.10 · Duplication 0.08.

## Packaged model & debt projection (Member 2, B4)

```powershell
python -m ml.train                 # evaluate + pick the model         -> data/models/risk_model.joblib
python -m ml.package               # calibrate + production model     -> data/models/production.joblib
python -m ml.predictor data/processed/psf__requests_latest_features.csv
python -m ml.forecast pallets__flask          # add --json for the chart data
```

```python
from ml.predictor import predict, RiskPredictor
predict({"loc": 1184, "commit_count": 735, ...})   # one file -> dict (missing features = unknown)
RiskPredictor.load().predict(scan.features)        # risk_score, risk_level, priority_rank,
                                                   # explanation, factors, recommendation, model_version
from ml.forecast import debt_timeline
debt_timeline("pallets__flask")                    # history + projection + trend for the chart
```

**Calibration (Platt scaling, leak-free):** raw scores were inflated by balanced class weights
(average 0.40 vs a real rate of 0.10). The calibrator is fitted on out-of-time predictions.
On the 2023+ test set the average predicted risk is 0.08 vs 0.10 actual, calibration error drops
0.30 → 0.02 and the Brier score 0.196 → 0.080. Ranking is unchanged. SHAP impacts are scaled by the
calibration slope, so they still add up exactly to the calibrated score.

**Risk levels** (calibrated probability; shared with `backend/app/services/risk.py`), chosen from
what actually happened on the test set:

| Level | Risk score | Files that really got bug fixes (2023+) |
|---|---|---|
| Critical | ≥ 0.35 | ~40% (3–4× average, top ~3% of files) |
| High | 0.20–0.35 | ~29% |
| Medium | 0.10–0.20 | ~21% |
| Low | < 0.10 | 2–10% |

**Production model:** same settings, refitted on all 3,051 labelled rows. The calibrator comes from
2,170 out-of-time predictions (2016–2025).

**Projected technical debt:** per snapshot, *expected bug-prone files* (sum of risk scores) and
*risk-weighted KLOC* (sum of risk × size); a linear trend through the last 6 snapshots projects
6/12/18 months ahead with a 95% band. Fair backtest (model trained before 2023, 27 repo snapshots
from 2023 on): mean error 2.10 files vs 2.26 for "same as last time", but it under-predicts the
total (59 vs 76). Trends today: flask flat, requests flat, click rising, httpx falling.

## Backend ↔ pipeline ↔ model (Member 3, C1)

```powershell
.\venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt     # includes pipeline + ml requirements
cd backend; uvicorn app.main:app --reload   # needs data/models/production.joblib (ml.train + ml.package)
```

`POST /api/repositories/{id}/scans` answers `202 pending` at once. A background job
(`backend/app/services/analysis.py`) then:

1. clones/updates the repo and computes every file's features (`pipeline.scanner`)
2. scores them with the calibrated model + SHAP + advice (`ml.predictor`)
3. stores per-file results (`file_analyses`: score, level, rank, metrics, explanation, factors,
   recommendation) and the repo's commit history
4. on a repo's **first** scan, also scores 6 past snapshots (every 6 months), so trends and the
   debt forecast have data straight away
5. sets the scan `completed`, or `failed` with a readable `error_message`

Poll `GET /api/scans/{id}`. New endpoint for the debt chart: `GET /api/repositories/{id}/debt-forecast`
(history + 6/12/18-month projection with 95% band + trend direction).

Repos with no Python files (e.g. a TypeScript/React app) fail with a clear explanation that names
the languages found, instead of a model error: the model is trained on Python code only.
Robustness: missing/private repos fail in ~2 s with a clear message (git never waits for a
login prompt), half-finished clones are removed, and scans interrupted by a server restart are
marked failed at startup instead of blocking new ones. Data paths are anchored to the project
root (`pipeline/paths.py`, override with `RISK_DATA_DIR`). End-to-end on `pallets/flask`: ~20 s for
the first scan (35 files + 6 history points). Background tasks run in-process; a job queue
(RQ/Celery) is the upgrade path for many users.

## GitHub App: automatic PR risk comments (Member 3, C2)

`POST /api/github/webhook` receives GitHub events:

| Event | What happens |
|---|---|
| `pull_request` opened / synchronize / reopened / ready_for_review | Background review of the Python files the PR adds or changes: risk at the PR head vs the base branch, then **one** PR comment (created the first time, **updated** on later pushes) |
| `push` to the default branch | A normal scan, so the dashboard stays fresh |
| `installation`, `installation_repositories` | Remembers which App installation covers which repo (needed to comment) |
| `ping` | Answers `pong` |

Security: every request must carry a valid `X-Hub-Signature-256` HMAC. With no secret configured,
all webhooks are refused. Redelivered events are ignored. PR reviews are stored as
`pull_request` scans (with `report_markdown`) and kept out of the repo's trends / debt forecast.

**Set it up (once):**
1. GitHub → Settings → Developer settings → **GitHub Apps → New GitHub App**
   - Webhook URL: `https://<your-server>/api/github/webhook` (locally: forward with
     [smee.io](https://smee.io) or ngrok to `http://localhost:8000/api/github/webhook`)
   - Webhook secret: a long random string
   - Permissions: **Pull requests: Read & write**, **Contents: Read**, Metadata: Read
   - Subscribe to events: **Pull request**, **Push**
2. Generate a **private key** (downloads a `.pem`) and note the **App ID**.
3. Install the App on your repositories, and add the same repos in the dashboard.
4. `backend/.env`:
   ```
   GITHUB_WEBHOOK_SECRET=<the secret>
   GITHUB_APP_ID=<app id>
   GITHUB_PRIVATE_KEY_PATH=C:/path/to/your-app.private-key.pem
   DASHBOARD_URL=http://localhost:5173
   ```
   Quick alternative for testing without an App: `GITHUB_TOKEN=<personal access token>`.
   Without either, the report is still built and stored on the scan, just not posted.

Tested end to end against real flask PR #6168, with GitHub's API replaced by a fake server that
checks the App JWT signature, the token exchange, comment creation and comment update.

## Deployment: Docker, PostgreSQL, Render (Member 3, C3)

**Locally with Docker** (API + PostgreSQL), needs Docker Desktop:
```powershell
copy .env.example .env      # then fill in SECRET_KEY (and GitHub settings if used)
docker compose up --build   # -> http://localhost:8000/docs
```

**On Render:** push the repo to GitHub → Render Dashboard → New → **Blueprint** → pick the repo.
`render.yaml` creates the API (Docker) and a PostgreSQL database, wires `DATABASE_URL` and
generates `SECRET_KEY`. Set `CORS_ORIGINS`/`DASHBOARD_URL` to the frontend URL and, for PR
comments, the GitHub App settings. Point the GitHub App's webhook to
`https://<your-api>.onrender.com/api/github/webhook`. **AWS** works the same way with the
same image: App Runner or ECS for the container, RDS PostgreSQL for `DATABASE_URL`, an EFS
volume for `/data`.

| Piece | What it does |
|---|---|
| `Dockerfile` | Python 3.13 slim + git; CPU-only PyTorch; non-root user; model baked in (`RISK_MODEL_PATH`); `/data` volume for clones/caches/emotion model; health check |
| `docker/entrypoint.sh` | Waits for the database, runs `alembic upgrade head`, starts uvicorn |
| `backend/migrations/` | Alembic migrations (initial schema). After changing a model: `alembic revision --autogenerate -m "..."` |
| `docker-compose.yml`, `.env.example` | API + PostgreSQL 17 with persistent volumes |
| `render.yaml` | Render Blueprint: web service + database + disk |

**Production safety:** with `ENVIRONMENT=production` the API **refuses to start** if `SECRET_KEY`
is the default/short, `CORS_ORIGINS` is `*`, or the database is SQLite. Render's `postgres://`
URLs are converted for the psycopg driver automatically. ML library versions are pinned
(`ml/requirements.txt`) because the saved model must be loaded with the versions it was trained
with. `data/models/production.joblib` (78 KB) is committed so cloud builds include it.

**Resources:** PyTorch + the emotion model need ~1.5–2 GB RAM. On a small (512 MB) server set
`RISK_USE_HF=0`; the AI emotion signal is then left unknown and the model fills it in.

**Tested:** Alembic migration + a full flask scan through the API on a real PostgreSQL 17.9
server (4,373 commit rows, enums, JSON, search, cascade delete). Not tested here: building and
running the Docker image (Docker isn't installed on this machine) and the Render deploy itself.

## Tests & error handling (C4)

```powershell
pip install -r requirements-dev.txt
python -m pytest          # 50 tests, ~30 s, fully offline
```

The tests build a small **synthetic git repository** (60 dated commits by 3 authors, bug fixes,
late-night commits, a rename, and a PR branch) and run the *real* pipeline, model and API on it.
GitHub is replaced by that repo and a fake API server; the emotion model is switched off; data and
database live in a temp folder that is deleted afterwards.

| Area | What is checked |
|---|---|
| Pipeline (23) | bug-fix rules, broken timezones, vendored/bot filters, rename tracking, cut-off dates, nesting/coupling/duplication, Python 2 code, **no future data in features**, labels = bug fixes in the next 6 months, incremental cache == full parse, scanner columns == training columns |
| Model (7) | message lexicon, backend/ML thresholds identical, risk levels, single-file `predict()` with missing features, **SHAP adds up exactly** to the calibrated score, low-risk files get no advice, debt projection |
| Backend (20) | sign-up/login, token checks, same error for wrong password vs unknown user, **login lockout**, URL validation, **users can't see each other's data**, scan job end to end (ranking, explanations, history back-fill, trends, debt forecast, file history, filters/sorting/paging), failed scans + restart recovery, webhook signatures, fail-closed, oversized/invalid payloads, PR review posts then **updates** one comment, push/installation events, hidden 500 errors |

**Error handling added:**
- Unexpected errors return `{"detail": "Internal server error", "request_id": ...}`. The traceback is
  logged but never sent to the client (no stack traces, SQL or file paths leak).
- Every response carries an `X-Request-ID` (or reuses the caller's), so a user's error report can be
  matched to the server log.
- Login brute-force protection: 5 failed attempts for an email within 5 minutes → `429` with
  `Retry-After`.
- Webhook payloads over 25 MB → `413`, invalid JSON → `400`; repo URLs are capped at 500 characters.

## Frontend (Member 4, `frontend/`)

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173  (start the backend on :8000 first)
npm run build      # type-check + production build into dist/
```

React 18 + TypeScript + Vite, Tailwind CSS, Zustand, React Router. In development Vite forwards
`/api` to the backend at `127.0.0.1:8000`, so no CORS setup is needed. In production, set
`VITE_API_URL` to the API's URL and add the frontend's URL to the backend's `CORS_ORIGINS`.

| File | Purpose |
|---|---|
| `src/api/client.ts` | Every backend call: adds the login token, turns FastAPI errors (incl. 422 field lists, 429 lockout) into readable messages, logs out on an expired token |
| `src/api/types.ts` | TypeScript shapes of the backend's responses |
| `src/store/auth.ts` | Zustand login state (token saved in localStorage, so a refresh stays logged in) |
| `src/components/RequireAuth.tsx` | Logged-in pages redirect to login (then back); login/register redirect to the dashboard when already logged in |
| `src/components/ui.tsx` | Shared Button / Input / Alert / Spinner / Logo; risk colours live in `tailwind.config.js` |
| `src/pages/` | Login, Register (checks the same rules as the backend before sending), Dashboard |

Tested in the browser against the real backend: redirect when logged out, field errors,
sign-up → auto-login → dashboard, refresh keeps the session, sign-out, duplicate email message,
and the login lockout message after 5 wrong passwords. Both phone and desktop layouts work.

**Repositories (D2):**
- `src/store/repos.ts` (Zustand) holds the list and the actions: add (optionally "Add & scan"),
  start scan, delete.
- `src/pages/DashboardPage.tsx`: add form (rejects non-GitHub links before sending) and one card
  per repo. Each card shows the scan status (queued / scanning / scanned / failed + reason), the
  latest report's files per risk level as a bar, and View report / Rescan / Delete (with a confirm
  dialog: focus on Cancel, Escape closes).
- **Live updates:** while a scan is queued or running, the page refreshes itself every 3 s
  (`src/hooks.ts`, paused when the browser tab is hidden).
- `src/pages/RepoPage.tsx` (`/repos/:id`): latest report summary and scan history (D3 adds the full
  report).
- Backend: repository responses now include `risk_counts` + `report_scan_id` from the latest
  *completed* scan, so a card keeps showing the last report while a new scan runs. Failed scans
  show a plain message for problems the user can fix (missing/private repo).

**Scan report (D3)**, on `/repos/:id` (`src/components/report/`):
- **Summary cards:** files analysed, files needing attention (critical + high), *expected bug-prone
  files* (sum of the calibrated risks), model version.
- **Donut chart** (Recharts) of files per risk level; clicking a slice or legend row filters the table.
- **Code quality averages** with the tools' own scales: McCabe complexity (≤10 simple, ≤20 moderate),
  Radon maintainability (A ≥ 20, B 10–19, C < 10), duplication %. Test coverage is shown as "not
  measured" (the model uses has-a-test-file instead).
- **Prioritised ranking table:** rank, path, risk % + level, main reasons (top SHAP factors), complexity,
  lines, commits, bug fixes. Level filter chips with counts, debounced path search, sort (priority /
  complexity / churn / bug fixes / developers / size), 25 per page. "Why?" opens the recommendation
  and SHAP factor bars (red raises, green lowers). Extra columns hide on small screens.
- Filters live in the URL (`?level=high&sort=loc&page=2`), so a view can be bookmarked or shared.
- If a new scan is running, the previous report stays visible with a notice.
- The report page is code-split: the charting library (~110 kB compressed) only loads when a report is
  opened. Login and the dashboard stay at ~63 kB.

**Codebase heatmap (D4)**, the "Codebase heatmap" tab on a repo page (`src/components/heatmap/`):
- A treemap (layout with `d3-hierarchy`, drawn with React): every box is a file, nested inside its
  folders. **Size** = lines of code, or number of commits (toggle: a "hotspot" view of where changes
  concentrate). **Colour** = predicted risk, a gradient with stops at the level thresholds
  (green → yellow 10% → orange 20% → red 35%+).
- **Zoom:** click a folder label to zoom in (boxes animate to their new place), use the breadcrumb to
  go back. Single-child folders are merged (`src/flask`) to save space.
- **Hover** a box for a tooltip (risk, lines, commits, bug fixes, main reasons; for folders: files,
  expected bug-prone files, riskiest file). **Click** a file for a side panel with metrics, SHAP factor
  bars and the recommendation.
- The tab and zoomed folder are in the URL (`?view=heatmap&folder=src/flask`). All files are loaded in
  pages of 200 (capped at 3,000). Every box is a keyboard-focusable button with a spoken label.

**File page & debt chart (D5)** (`src/pages/FilePage.tsx`, `src/components/charts/`):
- **Projected technical debt over time** on the report tab: solid line = measured at past scans,
  dashed line + shaded band = 6/12/18-month projection with 95% range, "Today" marker, trend badge
  (e.g. "▼ falling · −0.27 files/year"). Toggle between *expected bug-prone files* and
  *risk-weighted code size*. Data from `GET /api/repositories/{id}/debt-forecast`.
- **File page** `/repos/:repo/scans/:scan/files/:file` (opened from the table's file names, "Why?"
  and the heatmap panel): risk + rank, GitHub link (exact commit), "What to do", two SHAP charts
  (by factor and by individual metric with its value; red raises, green lowers), risk-over-time chart
  with the level bands behind it, recent commits (bug fixes tagged, linked to GitHub) and every
  measurement in 4 groups (code, history, team/coupling/tests, commit-message NLP).
- `/repos/:id/scans/:scan`, the link used in PR comments, opens the repo's report.
- Charts are code-split: Recharts is shared by the report and file pages and loads only there.

**Polish (D6):**
- **Error screens:** an error boundary per page shows a friendly message (Reload / Go to dashboard)
  instead of a blank page, and the top bar keeps working. After a new deployment, a stale tab that
  can't load a page's code gets "A new version is available → Reload". `/__crash` (development
  builds only) triggers it for testing.
- **Session expired:** an expired login token sends you to the login page with an explanation;
  signing in returns you to the page you were on.
- **Offline banner** while the browser has no connection.
- **Loading skeletons** in the report's shape (no layout jump); invalid addresses (`/repos/abc`,
  missing files) show "not found" instead of an error.
- **Accessibility:** "Skip to content" link, a page title per page (`pallets/flask · Code Risk
  Predictor`), scroll to top on navigation, reduced-motion support (no sliding heatmap animation, no
  pulsing skeletons), favicon.
- **Phones:** checked every page at 375 px with no sideways scrolling. On small screens the ranking
  shows file name + coloured dot + % + "Why?" in one row, the scan history is compact, and the SHAP
  charts use narrower labels.

Tested live: added `pallets/flask` → "Queued" → "Scanning…" → the card filled in by itself
(1 critical, 3 high, 4 medium, 27 low) without reloading. Also tested: rejected non-GitHub link,
duplicate repo, a missing repo failing with a clear reason, and cancel/confirm delete.

## Roadmap (built one part at a time)

**Phase A — Data pipeline (Member 1)**
- [x] A1 — Clone repo + extract Git history (who/when/how often, churn, developers, bug-fix commits), per-file history features with a cutoff date
- [x] A2 — Static analysis: Python `ast` (nesting depth, functions, classes, imports → coupling) + Radon (complexity, maintainability) + Lizard; duplication; has-tests signal
- [x] A3 — Dataset builder: time-based snapshots (features up to date T, label = bug fixes in the next 6 months) → clean CSV for the ML engineer
- [x] A4 — Automated pipeline: `scan_repository(url)` end to end, incremental refresh (keeps feeding fresh data)

**Phase B — Machine learning (Member 2)**
- [x] B1 — Commit-message NLP: frustration / rushed-work signals (lexicon + HuggingFace sentiment)
- [x] B2 — Train & compare baseline, Random Forest, XGBoost with time-based split; tuning; overfitting checks
- [x] B3 — SHAP explanations + actionable recommendations
- [x] B4 — Package model behind `predict(file_data)`; projected technical-debt trend

**Phase C — Backend (Member 3)** — Parts 1–4 done (skeleton, DB schema, JWT auth, 11 dashboard APIs, demo data)
- [x] C1 — Connect pipeline + model to scans (background jobs replace dummy scores)
- [x] C2 — GitHub App webhooks: PR opened → scan → predict → automated PR comment
- [x] C3 — Docker + PostgreSQL + Render/AWS deploy
- [x] C4 — Automated tests & error handling

**Phase D — Frontend (Member 4)**
- [x] D1 — React + Vite + Tailwind + Zustand setup, login/register
- [x] D2 — Repositories page: list + add by URL + start scan
- [x] D3 — Scan report: prioritised risk table, risk-level pie, quality averages
- [x] D4 — Interactive zoomable codebase heatmap (folders → files, red = risky, green = safe)
- [x] D5 — File detail (SHAP chart, recommendation, history) + "Projected Technical Debt Over Time" chart
- [x] D6 — Polish: loading/error states, responsive layout

**Phase E — Ship**
- [x] E1 — Deploy, architecture docs, demo script for the presentation
  (deploy-ready: one Docker image serves dashboard + API; Render blueprint. The actual Docker build
  and Render deploy still need Docker Desktop / a Render account — see `docs/DEPLOYMENT.md`)

## Documentation

| Document | For |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | system, components, scan and PR flows, data model, deployment (diagrams) |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | run locally, Docker Compose, Render, environment variables |
| [docs/DEMO.md](docs/DEMO.md) | 10-minute demo script for the faculty presentation |
| [docs/Team_Study_Guide.md](docs/Team_Study_Guide.md) | each member's part, full technical A–Z, viva questions |
