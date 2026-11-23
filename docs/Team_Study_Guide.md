# AI-Powered Code Complexity & Technical Debt Predictor
## Team Study Guide

Read this so that every member can explain their own part in depth, understand the other three
parts, and answer the faculty's questions about the whole project.

**How this guide is organised**

- **Part 0 — The project in 5 minutes** (everyone reads first)
- **Part A — Individual contributions**: one chapter per member (your own chapter = learn deeply)
  - A1. Member 1 — Code Data Engineer (data extraction & processing)
  - A2. Member 2 — ML & AI Scientist (prediction, NLP, explainability)
  - A3. Member 3 — Backend & Integrations Architect (APIs, database, GitHub App, deployment)
  - A4. Member 4 — Frontend & Data Viz Engineer (dashboard, heatmap, charts)
- **Part B — Full technical A–Z** (everyone): the whole system end to end, every algorithm,
  all numbers, API, database, security, testing, deployment, how to run, glossary A–Z
- **Part C — Summary for all members**: one-minute pitch, key numbers, limitations,
  demo script for the faculty, common viva questions

Each member chapter has the same shape: *role → what you built → files you own → key concepts
you must be able to explain → numbers to remember → problems you solved → what to demo →
viva questions with answers.*

---

# PART 0 — THE PROJECT IN 5 MINUTES

## 0.1 The problem

Technical debt builds up silently. Some files become complex, change constantly and attract bugs,
and teams only notice when deadlines slip or production breaks. Teams lack a simple tool that
looks at the code *and* its history and says **"these files are likely to need bug fixes in the
next few months — fix them first, and here is why."**

## 0.2 Our solution

A web platform where a user pastes a GitHub repository link and gets:

1. a **risk score for every Python file** = the probability that the file will need a bug fix in
   the next 6 months,
2. a **risk level**: Critical / High / Medium / Low,
3. an **explanation** of why (SHAP): e.g. "size +1.09, change activity +0.66, coupling +0.52",
4. a **recommendation** ("Split this 1,686-line file…"),
5. **visuals**: a prioritised ranking table, a zoomable red/green **codebase heatmap**, a
   **"Projected Technical Debt Over Time"** chart, and per-file history,
6. **automatic GitHub pull-request comments** with the risk of the files a PR changes.

## 0.3 The pipeline (who does what)

```
 GitHub repo URL
      |
      v
 [MEMBER 1  pipeline/]  clone repo -> Git history (commits, churn, developers, bug fixes)
                         + static analysis (complexity, size, nesting, coupling, duplication)
                         -> one row of ~43 numeric features per file
      |
      v
 [MEMBER 2  ml/]         commit-message NLP -> trained model (logistic regression)
                         -> calibrated risk score + level -> SHAP explanation + advice
                         -> technical-debt projection
      |
      v
 [MEMBER 3  backend/]    FastAPI REST API + database (users, repos, scans, results, history)
                         background scan jobs, GitHub App webhooks -> PR comments,
                         Docker / PostgreSQL / Render deployment, 52 automated tests
      |
      v
 [MEMBER 4  frontend/]   React dashboard: login, repositories, risk report, heatmap,
                         file pages, debt chart
```

## 0.4 Technology stack

| Member | Area | Technologies |
|---|---|---|
| 1 | Data pipeline | Python, GitPython, `git log`, Python `ast`, Radon, Lizard, pandas |
| 2 | ML & NLP | scikit-learn, XGBoost, Random Forest, HuggingFace Transformers + PyTorch, SHAP |
| 3 | Backend | FastAPI, SQLAlchemy, SQLite (dev) / PostgreSQL (prod), Alembic, JWT, bcrypt, GitHub Webhooks, Docker, Render |
| 4 | Frontend | React 18, TypeScript, Vite, Tailwind CSS, Zustand, React Router, Recharts, d3-hierarchy |

## 0.5 Folder map

```
ai-code-risk-predictor3/
  pipeline/    Member 1: git_history, static_analysis, dataset, store, scanner, run, filters
  ml/          Member 2: nlp, train, models, explain, package, predictor, forecast
  backend/     Member 3: FastAPI app (app/), migrations/, requirements
  frontend/    Member 4: React app (src/)
  tests/       52 automated tests (pipeline, ml, backend)
  data/        generated: repos/ (clones), cache/, processed/ (datasets), models/ (trained model)
  Dockerfile, docker-compose.yml, render.yaml, docker/entrypoint.sh   deployment
  README.md    full technical README
```

## 0.6 Headline results (memorise these)

- Dataset: **3,051 rows** (file × snapshot) from **4 real Python repos** (requests, flask,
  click, httpx), **95 snapshots** (2011–2026), **14.4 %** of rows "bug-prone".
- Model: **logistic regression**, test ROC-AUC **0.80** (95 % range 0.77–0.83), finds **63 %** of
  future bug-prone files in the top 20 % of files, **≈3× better than random** at picking the top 5.
- Works on a **repository it has never seen**: ROC-AUC 0.79–0.86.
- Honest finding: statistically **tied with the simple rule "biggest files first"**.
- Calibration: average predicted risk **0.40 → 0.08** (real rate 0.10); calibration error **0.30 → 0.02**.
- **52 automated tests** pass; tested on real **PostgreSQL 17.9**.

---

# PART A — INDIVIDUAL CONTRIBUTIONS

---

## A1. MEMBER 1 — CODE DATA ENGINEER (Data Extraction & Processing)

### Your role in one sentence
You turn a GitHub repository into clean numbers: who changed each file, when, how much, how often
it was bug-fixed, and how complex its code is — and you build the time-correct dataset the ML
model learns from, plus the automated pipeline that keeps it fresh.

### What you built (parts A1–A4)

| Part | What | Main file | Output |
|---|---|---|---|
| A1 | Clone repo + Git history extraction, bug-fix detection, rename tracking | `pipeline/git_history.py` | commits table + per-file history features |
| A2 | Static code analysis (AST, Radon, Lizard, coupling, duplication, test links) | `pipeline/static_analysis.py` | 27 metrics per file, at any past commit |
| A3 | Time-based training dataset with future labels (no leakage) | `pipeline/dataset.py` | `data/processed/dataset.csv` (3,051 rows) |
| A4 | Automated pipeline: cache, incremental refresh, live scanner, CLI | `pipeline/store.py`, `scanner.py`, `run.py` | `python -m pipeline.run scan/dataset/refresh` |

Helper files you also own: `pipeline/filters.py` (which files count — skips vendored code),
`pipeline/paths.py` (where data lives), `pipeline/errors.py` (user-friendly errors),
`pipeline/repos.txt` (training repos).

### A1 — Git history (`git_history.py`)

- **Cloning**: `clone_repo(url)` clones into `data/repos/<owner>__<repo>` once, then pulls
  (fast-forward) on later runs. Never waits for a login prompt (private/missing repo fails in ~2 s).
- **Parsing history**: one call to `git log --no-merges -M --numstat -z` with a custom format.
  Control characters (`\x1e`, `\x1f`, `\x1d`) separate fields safely. For every (commit, file):
  sha, date, author, email, lines added, lines deleted, change type, message, bug-fix flag.
- **Renames are followed**: the log is read newest→oldest with an alias map (old path → latest
  path). So `requests/models.py` (old name) and `src/requests/models.py` are one file with
  **735 commits**, not 18.
- **Bug-fix detection** (keyword heuristic, as in SZZ research):
  - counts as fix: "fix", "bug", "hotfix", "patch", "crash", "regression", "broken", "incorrect"…
    or "Fixes #123" / "closes #45" anywhere in the message,
  - does **not** count: fixes of typos, docs, README, whitespace, lint, formatting, CI, build,
    mypy/flake8/black/isort/ruff/typing,
  - a "fix" touching **more than 10 files** is a bulk change (CI repair, reformat), not a targeted fix.
- **Per-file history features** (`file_history_features(commits, until=T)`), using only commits
  **before** date T: commit_count, lines added/deleted, churn (added+deleted), bug_fix_count,
  bug_fix_ratio, num_developers (bots excluded), top_author_share (ownership), recent commits/churn
  (last 90 days), age_days, days_since_last_change.
- Uses the Unix timestamp (`%at`) for dates and parses the timezone separately and tolerantly.
- Merges author aliases with `.mailmap`; ignores bots (dependabot, github-actions).

### A2 — Static analysis (`static_analysis.py`)

- Reads files **straight from Git objects** at any commit (`repo.commit(sha).tree`) — no
  checkout needed, so we can measure the code "as it was" on any past date.
- Per file:
  - **Python `ast`**: number of classes, imports, **max nesting depth** (if/for/while/try/with/match;
    an `elif` chain is not counted as deeper),
  - **Lizard** (token-based, works even on Python 2 code): cyclomatic complexity per function
    (avg/max/total), function length, max parameters,
  - **Radon**: lines of code, source lines, comments, comment ratio, **maintainability index**,
    Halstead volume.
- Repo-wide:
  - **coupling**: internal import graph → **fan-in** (how many files import it), **fan-out** (how
    many internal files it imports), coupling = fan-in + fan-out, instability = fan-out/(fan-in+fan-out);
    relative imports like `from ..models import X` are resolved,
  - **duplication**: % of a file's lines inside a block of ≥6 normalised lines that also appears
    elsewhere (hash-based clone detection),
  - **test links**: is there `test_<name>.py`? how many test files import this file?
    (proxy for test coverage, which we don't measure directly).
- `parse_ok` marks files that are not valid Python 3 (old Python 2 code): Lizard metrics still work.

### A3 — Dataset builder (`dataset.py`) — the most important idea for the viva

Every 6 months in a repo's history we take a **snapshot at date T**:

- **features** = Git history **before T** + code metrics of the files **as they were at T**,
- **label** = what happened in the **next 6 months (T → T+6)**: number of bug-fix commits
  (`future_bug_fixes`), commits, churn; `label_bug_prone = 1` if at least one bug fix.

Rules that prevent cheating ("data leakage"):
- features never look after T, labels never before T,
- snapshots whose 6-month window isn't finished yet are dropped,
- 12 months of "warm-up" history before the first snapshot,
- rename-aware: the path at T is mapped to the file's latest name so history and labels join,
- test files are excluded by default (they change *because* of fixes elsewhere).

Verified by hand: one row's features (491 commits before T) and label (9 future bug fixes)
matched a manual count from the raw commits.

### A4 — Automated pipeline (`store.py`, `scanner.py`, `run.py`)

- **Commit cache** (`data/cache/`): a repo's parsed history is stored; next time only **new
  commits** (`last_sha..HEAD`) are parsed and appended. If history was rewritten (force-push),
  it re-parses everything. A cache version number forces a rebuild when columns change.
  Proven: incremental result == full re-parse, even across the big rename.
- **Static-analysis cache**: results stored per commit sha (past code never changes).
- **Scanner** `scan_repository(url)`: clone/update → commits (+NLP signals) → features of
  today's code (exactly the training feature columns) → optional past snapshots (for trend
  charts) → commits table. Used by the backend and the GitHub webhook.
- **CLI**:
  - `python -m pipeline.run scan <url>` — features of today's code,
  - `python -m pipeline.run dataset` — training set from `pipeline/repos.txt`,
  - `python -m pipeline.run refresh --every 360` — keeps feeding fresh data every 6 h.
- Speed: first full run ~4.5 min (mostly downloading), refresh ~40 s.
- Non-Python repos (e.g. a TypeScript/React app) give a clear message naming the languages found.

### Key concepts you must be able to explain
1. Why we follow **renames** (otherwise a moved file loses its whole history).
2. How **bug-fix commits** are detected and the limits of keywords (heuristic, can be wrong).
3. **Churn** = lines added + deleted (how much a file changes).
4. **Cyclomatic complexity** = number of independent paths through a function (each if/for/while/and/or adds one).
5. **Maintainability index** (Radon, 0–100): combines Halstead volume, complexity and lines; higher = easier.
6. **Fan-in / fan-out / coupling**: dependency graph from imports.
7. **Time-based snapshots** and **leakage**: why features use only the past and labels only the future.
8. **Vendored code**: third-party code copied into a repo (e.g. `requests/packages/`) — skipped.
9. **Incremental cache** and why it must equal a full re-parse.

### Numbers to remember
- requests: 2,699 commits on 76 source files (after vendor filter), 460 bug-fix commits.
- 27 static metrics per file; ~43 features per file in total (with history + NLP).
- Dataset: 3,051 rows, 95 snapshots, 4 repos, 14.4 % bug-prone (439 positives).
  flask 1,287 rows · click 912 · requests 548 · httpx 304.
- 2013 snapshot analysis: 62 s → 0.7 s after skipping vendored code.
- Refresh: 4.5 min → 40 s with caches.

### Problems you solved (great viva material)
| Problem | Cause | Fix |
|---|---|---|
| Crash on a 2011 commit | broken timezone "+518:00" in Git data | use Unix timestamp `%at`; parse timezone tolerantly |
| `models.py` showed 18 commits instead of 735 | files moved `requests/` → `src/requests/` | `-z --numstat -M` + alias map, newest→oldest |
| 2013 snapshot took 62 s | vendored chardet frequency tables (huge data files) | skip vendored folders (`filters.py`): 0.7 s |
| Python 2 files unparseable | `print "x"` is not Python 3 | Lizard (token-based) still measures them; `parse_ok` flag |
| Fake spike: 12 files "bug-prone" | one "Fix CI and build failures" commit touched 12 files | not-fix words (CI, build, lint…) + >10-file rule |
| Incremental cache ≠ full parse | first-file "ADD" label overwrote "RENAME" | only promote MODIFY → ADD |
| Scan could hang forever | Windows Git opened a login window for missing/private repos | `GIT_TERMINAL_PROMPT=0`, clear `RepoNotFound` error |
| TypeScript repo crashed the model | no Python files → 0 rows | `NoSourceFiles` error with languages found |

### What you demo
```
python -m pipeline.git_history https://github.com/psf/requests
python -m pipeline.static_analysis data/repos/psf__requests --rev 2016-01-01
python -m pipeline.run refresh
```
Show `data/processed/dataset.csv` (rows = file × snapshot, columns = features + labels).

### Viva questions you should be ready for
- **Q: Where does your data come from?** From the Git history and source code of 4 public Python
  GitHub repositories, extracted by our own pipeline; no ready-made dataset.
- **Q: How do you know a commit fixed a bug?** Keyword heuristic on the commit message (fix, bug,
  crash, "fixes #123"…), excluding typo/docs/CI/lint fixes and bulk commits touching >10 files.
  It's the standard approach in defect-prediction research (SZZ-style); it is not perfect.
- **Q: What is data leakage and how did you avoid it?** Using information from the future to
  build features. Our features use only commits before T and code at T; labels use only T→T+6;
  incomplete windows are dropped.
- **Q: Why not just analyse today's code?** Then we'd have no labels: we need to know what
  happened *after* the measurement. Snapshots in the past give us both.
- **Q: How do you measure complexity?** Lizard computes McCabe cyclomatic complexity per function;
  we keep max/avg/total per file, plus nesting depth from the AST.
- **Q: What is coupling?** fan-in + fan-out from the internal import graph.
- **Q: Why skip vendored code?** The team doesn't maintain it, so its risk is meaningless, and it
  was huge and slow.
- **Q: How does the pipeline stay fresh?** `refresh` pulls repos, parses only new commits
  (cache), rebuilds features and the dataset; `--every N` repeats it.

---

## A2. MEMBER 2 — ML & AI SCIENTIST (Prediction, NLP, Explainability)

### Your role in one sentence
You turn Member 1's feature table into a trustworthy risk score: NLP signals from commit
messages, a model trained and evaluated without cheating, calibrated probabilities with risk
levels, SHAP explanations with advice, and a technical-debt projection — packaged behind
`predict(file_data)`.

### What you built (parts B1–B4)

| Part | What | Main file | Output |
|---|---|---|---|
| B1 | Commit-message NLP (frustration, rushed work, timing) incl. HuggingFace emotion model | `ml/nlp.py` | 8 `msg_*` features |
| B2 | Train & compare models with a time-based split, tuning, overfitting checks | `ml/train.py`, `ml/models.py` | `data/models/risk_model.joblib`, `report.json` |
| B3 | SHAP explanations, factor groups, recommendations | `ml/explain.py` | per-file explanation + advice |
| B4 | Calibration, risk levels, production model, `predict()`, debt forecast | `ml/package.py`, `predictor.py`, `forecast.py` | `data/models/production.joblib` |

### B1 — Commit-message NLP (`nlp.py`)
Per commit:
- `msg_frustrated` — word list: stupid, again, finally, wtf, ugh, "!!"…
- `msg_rushed` — word list: wip, quick fix, hack, workaround, for now, forgot, oops…
- `msg_short` (≤3 words), `msg_revert`, `msg_words` (length)
- `msg_late_night` (22:00–06:00 in the author's own timezone), `msg_weekend`
- `msg_hf_frustration` — HuggingFace model `j-hartmann/emotion-english-distilroberta-base`:
  P(anger) + P(disgust). Scored once per commit and cached (7,035 messages took ~4 min).
Per file these are averaged over the file's commits before the snapshot date.

Measured value (AUC, 0.5 = useless; second number = among files with similar activity):

| Signal | AUC | At equal activity |
|---|---|---|
| HuggingFace frustration | **0.68** | **0.62** (best NLP signal) |
| Message length | 0.62 | 0.61 |
| Rushed-work words | 0.65 | 0.55 |
| Frustration words | 0.62 | 0.54 |
| Short messages | 0.47 | 0.40 (inverse: terse commits → *less* bug-prone) |
| Late night / weekend / revert | ≈0.50 | no signal |

Known limitation: the emotion model learned everyday English, so programming words fool it
("Killed now dead code", "Remove useless imports" read as anger). Averaged per file it still helps.

### B2 — Training & evaluation (`train.py`)
- **Test set**: snapshots from **2023 onwards** (764 rows, 76 bug-prone) — never used for training
  or tuning.
- **Training set**: only snapshots whose 6-month label window ends **before 2023** (2,168 rows) —
  otherwise training labels would peek into the test period.
- **Tuning**: random search with **expanding-window validation** (validate on 2019, 2020, 2021,
  2022, each time training only on earlier data). Model chosen by validation score, not test score.
- **Models compared**: baselines (biggest files first; most recently active), logistic regression
  (log-scaled, standardised, balanced class weights), random forest, XGBoost, and an ensemble.
- **Metrics** (not accuracy — 86 % of files are safe, so "always safe" would be 86 % accurate):
  ROC-AUC, PR-AUC, **recall@20 %** (share of bug-prone files caught in the top 20 % of files),
  **precision@5**, effort-aware recall@20 % of lines, 95 % bootstrap confidence intervals,
  leave-one-repo-out.

| Test set (2023+) | ROC-AUC (95 % range) | PR-AUC | Caught in top 20 % | Precision top 5 | Train AUC |
|---|---|---|---|---|---|
| Random | 0.50 | 0.11 | 21 % | 0.13 | – |
| Biggest files first | 0.81 (0.77–0.85) | 0.33 | 63 % | 0.36 | – |
| Most recently active | 0.63 (0.58–0.70) | 0.18 | 50 % | 0.33 | – |
| **Logistic regression (chosen)** | **0.80 (0.77–0.83)** | 0.31 | 63 % | 0.38 | 0.85 |
| Random forest | 0.81 (0.78–0.85) | 0.27 | 64 % | 0.37 | 0.93 |
| XGBoost | 0.74 (0.70–0.77) | 0.21 | 44 % | 0.25 | 0.98 (overfits) |
| Ensemble | 0.81 (0.78–0.84) | 0.28 | 65 % | 0.38 | 0.89 |

- Unseen repository (train on 3, test on the 4th): ROC-AUC **0.79–0.86**.
- Removing all 13 size features gives the **same** AUC (0.80): other features carry information.
- Why logistic regression: tied for best, least overfitting, simplest, easiest to explain with SHAP.

### B3 — Explainability (`explain.py`)
- **SHAP** (`LinearExplainer` for our logistic model; tree/model-agnostic explainers supported):
  for every file, how much each feature pushed its score up (+) or down (−) compared with a
  typical file (200 training rows saved as "background").
- **Exactness check**: base value + sum of SHAP values = the model's score, error ~1e-15.
- **Factors**: features summed into groups — Size, Complexity, Change activity, Bug history,
  Team/ownership, Coupling, Tests, Duplication, Commit messages. SHAP values add up, so grouping is
  exact, and it cancels confusing signs between overlapping features (size vs maintainability).
- **Recommendations** from the biggest risk-raising factors, filled with the file's own numbers,
  only when they make sense ("split this file" needs ≥400 lines; "assign an owner" needs ≥5
  developers); low-risk files get "no action needed".
- What drives risk overall (mean |SHAP|): Size 0.50 › Change activity 0.46 › Coupling 0.29 ›
  Tests 0.19 (having tests lowers risk) › Bug history 0.12 › Complexity 0.12 › Commit messages
  0.10 › Team 0.10 › Duplication 0.08.

### B4 — Calibration, levels, packaging, forecast
- **Calibration (Platt scaling)**: balanced class weights inflate scores. We fit
  p = sigmoid(a·score + b) on **out-of-time** predictions (each year predicted by a model trained
  only on earlier years).

| 2023+ test set | Before | After |
|---|---|---|
| Average predicted risk (real 0.10) | 0.40 | **0.08** |
| Calibration error | 0.30 | **0.02** |
| Brier score (lower = better) | 0.196 | **0.080** |

Ranking is unchanged; SHAP impacts are multiplied by `a` so they still add up exactly.

- **Risk levels** chosen from what really happened on the test set:

| Level | Risk score | Files that really got bug fixes |
|---|---|---|
| Critical | ≥ 0.35 | ~40 % (3–4× average, top ~3 % of files) |
| High | 0.20–0.35 | ~29 % |
| Medium | 0.10–0.20 | ~21 % |
| Low | < 0.10 | 2–10 % |

- **Production model**: same settings retrained on all 3,051 rows; calibrator from 2,170
  out-of-time predictions (2016–2025). `predict({...})` for one file, `RiskPredictor.predict(df)`
  for many: risk_score, risk_level, priority_rank, explanation, factors, recommendation, version.
- **Debt forecast** (`forecast.py`): per snapshot, *expected bug-prone files* (sum of risk scores)
  and *risk-weighted KLOC* (sum of risk × lines / 1000); straight-line trend through the last 6
  snapshots, projected 6/12/18 months with a 95 % band. Fair back-test: error 2.10 files vs 2.26 for
  "same as last time" (~7 % better), under-predicts the total (59 vs 76).

### Key concepts you must be able to explain
ROC-AUC, PR-AUC, recall@20 %, precision@5, class imbalance, time-based split, expanding-window
validation, overfitting (train vs test gap), bootstrap confidence interval, logistic regression,
random forest, XGBoost, SHAP and additivity, calibration / Platt scaling / Brier score, why
thresholds are data-driven, what NLP adds.

### Numbers to remember
43 features · train 2,168 / test 764 rows · test AUC 0.80 · top-20 % recall 63 % · precision@5
0.38 (random 0.13) · unseen repo 0.79–0.86 · XGBoost 0.98 train vs 0.74 test · calibration error
0.30→0.02 · thresholds 0.35 / 0.20 / 0.10 · HF frustration AUC 0.68.

### Problems you solved
| Problem | Fix |
|---|---|
| XGBoost memorised training years (0.98 vs 0.74) | rejected; chose logistic regression by validation score |
| Models tie with "biggest files first" | proved other features carry signal (no-size experiment = 0.80); reported honestly |
| Saved model couldn't be loaded outside the training script (`__main__` pickling) | moved helpers to `ml/models.py` |
| "Low maintainability lowers risk" (confusing sign) | group SHAP into factors |
| Safe file told to "split this 86-line file" | advice only above medium risk and when numbers justify it |
| Half of all files ≥ 0.35 (inflated scores) | Platt calibration |
| Critical cut-off 0.50 → only 1 of 764 files | thresholds from real outcomes |
| Forecast back-test used a model that had seen the answers | redone with a pre-2023 model |
| Empty input (non-Python repo) crashed scikit-learn | predictor returns an empty result |

### What you demo
```
python -m ml.train        # comparison table, ~3 min
python -m ml.package      # calibration report + production model
python -m ml.predictor data/processed/psf__requests_latest_features.csv
python -m ml.forecast pallets__flask
```

### Viva questions
- **Q: Why not accuracy?** Only ~14 % of rows are bug-prone; "everything safe" scores 86 %.
  We use ranking metrics (AUC, PR-AUC, recall@20 %, precision@5).
- **Q: Your model ties with "biggest files first" — is it useless?** No: it's 3× better than
  random at the top 5, generalises to unseen repos, explains *why*, and without size features it
  is just as good. The size effect is a well-known result in defect-prediction research.
- **Q: What is SHAP?** A method from game theory that splits a prediction into the contribution
  of each feature; contributions add up exactly to the prediction.
- **Q: What is calibration?** Making "0.3" really mean ~30 % chance. Platt scaling fits a
  logistic curve on out-of-time predictions.
- **Q: How did you prevent overfitting?** Time-based split, validation on later years only,
  regularisation tuned by validation, train-vs-test gap check, leave-one-repo-out.
- **Q: What does NLP add?** The emotion-model frustration score and message length add
  information beyond activity (AUC 0.62/0.61 at equal activity); timing adds nothing.

---

## A3. MEMBER 3 — BACKEND & INTEGRATIONS ARCHITECT (System & APIs)

### Your role in one sentence
You built the "engine room": the REST API the dashboard calls, the database, user accounts and
security, background scan jobs that run Member 1's pipeline and Member 2's model, the GitHub App
that comments on pull requests, deployment (Docker/PostgreSQL/Render) and the automated tests.

### What you built

| Part | What | Main files |
|---|---|---|
| 1 | FastAPI skeleton, config, CORS, health check | `backend/app/main.py`, `config.py`, `routes/health.py` |
| 2 | Database schema (5 tables, indexes) | `backend/app/models/*.py`, `db/session.py` |
| 3 | Accounts & security: register/login, bcrypt, JWT | `routes/auth.py`, `core/security.py`, `api/deps.py` |
| 4 | Dashboard REST APIs, demo data | `routes/repositories.py`, `routes/scans.py`, `seed_demo.py` |
| C1 | Scan job: pipeline + model → database, history back-fill, debt-forecast API | `services/analysis.py` |
| C2 | GitHub App webhooks → PR review → PR comment | `routes/github.py`, `services/github_app.py`, `services/pr_review.py` |
| C3 | Docker, docker-compose, Render blueprint, Alembic migrations, production checks | `Dockerfile`, `docker-compose.yml`, `render.yaml`, `backend/migrations/` |
| C4 | 52 tests, error handling, login lockout, request IDs | `tests/`, `services/rate_limit.py` |

### Database (5 tables)
| Table | Purpose | Key columns |
|---|---|---|
| `users` | accounts | email (unique), hashed_password, github_username |
| `repositories` | repos a user added | owner_id → users, full_name (unique per user), url, installation_id |
| `scans` | one analysis run | repository_id, trigger (manual/push/pull_request/history), status, commit_sha, pr_number, overall_risk, model_version, error_message, github_comment_id, report_markdown |
| `file_analyses` | per-file result | scan_id, file_path, risk_score, risk_level, priority_rank, commit_count, churn, num_developers, bug_fix_count, complexity, loc, coupling, duplication, maintainability, metrics (JSON), explanation (JSON), factors (JSON), recommendation |
| `commit_history` | mined Git history | repository_id, commit_sha, file_path, author, dates, lines, message, is_bug_fix |

Indexes on what the dashboard filters by (repo+file, scan+risk, repo+date). Deleting a user or
repo deletes everything under it (cascade).

### Security
- Passwords stored only as **bcrypt** hashes; 8–72 byte rule (bcrypt ignores bytes after 72).
- Login returns a **JWT** (signed token, 24 h); protected routes need `Authorization: Bearer <token>`.
- Same error for wrong password and unknown email (no email probing).
- **Login lockout**: 5 failures for an email in 5 minutes → 429 with Retry-After.
- **Data isolation**: another user's repo/scan returns **404, not 403** (don't reveal it exists).
- Webhooks must have a valid **HMAC-SHA256 signature**; no secret configured → refused (fail closed).
- Unexpected errors: logged with traceback, client only gets "Internal server error" + request ID.
- `ENVIRONMENT=production` refuses to start with a default secret key, `*` CORS or SQLite.

### The scan job (C1)
`POST /api/repositories/{id}/scans` answers **202 pending** immediately; a background task:
1. runs `scan_repository(url)` (Member 1),
2. scores with the calibrated model + SHAP + advice (Member 2),
3. stores file results and the commit history,
4. on the repo's **first** scan also scores **6 past snapshots** so trend charts aren't empty,
5. marks the scan **completed**, or **failed** with a readable reason.
Scans cut off by a server restart are marked failed at start-up.

### The GitHub App flow (C2)
1. Developer opens/updates a PR → GitHub sends `pull_request` to `POST /api/github/webhook`.
2. We verify the HMAC signature, ignore re-deliveries, find the registered repo.
3. Create a `pull_request` scan and answer immediately (GitHub expects < 10 s).
4. Background: fetch `refs/pull/<n>/head`, list changed Python files (`base...head`), score them
   on the PR head **and** on the base branch → show ▲/▼ change.
5. Sign in as the App: JWT signed with the App's private key (RS256) → exchange for a 1-hour
   installation token (cached) → **create one PR comment**, later pushes **update** the same comment.
6. Pushes to the default branch trigger a normal scan.
Tested against real flask PR #6168 with a fake GitHub API that verified the JWT and token exchange.

### Deployment (C3)
- `Dockerfile`: Python 3.13 slim + git, CPU-only PyTorch, non-root user, model baked in,
  `/data` volume, health check; entrypoint waits for the DB, runs `alembic upgrade head`.
- `docker-compose.yml`: API + PostgreSQL 17; `render.yaml`: one-click Render blueprint.
- Alembic migrations for safe schema changes; ML library versions pinned (pickled model).
- Tested on real **PostgreSQL 17.9** (migrations + full scan, 4,373 commit rows, cascade delete).
  Not tested here: building the Docker image (Docker not installed on the dev laptop).

### API you must know
Auth: `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`.
Repos: `POST/GET /api/repositories`, `GET/DELETE /api/repositories/{id}`.
Scans: `POST/GET /api/repositories/{id}/scans`, `GET /api/scans/{id}`,
`GET /api/scans/{id}/files` (filters, sort, paging), `GET /api/scans/{id}/files/{fid}`.
Charts: `GET /api/repositories/{id}/trends`, `/debt-forecast`, `/file-history?path=`.
GitHub: `POST /api/github/webhook`. Health: `GET /api/health`. Docs: `/docs` (Swagger).

### Problems you solved
| Problem | Fix |
|---|---|
| Only one user in the system could add a given repo | unique (owner_id, full_name) |
| Demo seed didn't save scans | add the root object last (SQLAlchemy 2.0 cascades) |
| Backend couldn't find model/caches (paths relative to start folder) | `pipeline/paths.py` anchored to project root |
| Scans stuck "running" after restart blocked new scans | mark interrupted scans failed at start-up |
| Back-filled history appeared as "latest" | order by date; trigger groups (BRANCH/LATEST) |
| PR scans polluted repo trends | PR scans excluded from trends/latest |
| Model unusable in Docker/Render | pin ML versions; commit the 78 KB model |
| Render gives `postgres://` URLs | auto-convert to `postgresql+psycopg://` |
| Test temp folders never deleted on Windows | git read-only files + helper processes: chmod + retry |
| PR report showed "≈ same" for a visible change | arrow when the change rounds to ±0.01 |

### Viva questions
- **Q: Why FastAPI?** Fast, async, automatic validation with Pydantic and automatic API docs.
- **Q: How does login work?** bcrypt-checked password → signed JWT with user id and expiry →
  sent as Bearer header; the server verifies the signature on every request.
- **Q: What happens when a PR is opened?** (the 6 steps above)
- **Q: How do you know a webhook really came from GitHub?** HMAC-SHA256 of the raw body with the
  shared secret, compared in constant time.
- **Q: Why background tasks?** Scans take seconds–minutes; the API must answer immediately.
  For many users we'd move to a job queue (RQ/Celery).
- **Q: Why Alembic?** To change the PostgreSQL schema safely without losing data.
- **Q: How do you test?** 52 pytest tests run offline on a synthetic Git repository with real
  pipeline + model + API; GitHub replaced by a fake server.

---

## A4. MEMBER 4 — FRONTEND & DATA VIZ ENGINEER (Dashboards & UI)

### Your role in one sentence
You built the web dashboard managers use: login, repository list with live scan status, the risk
report with charts and a ranked table, the zoomable codebase heatmap, file detail pages and the
"Projected Technical Debt Over Time" chart — responsive, accessible and robust to errors.

### What you built (parts D1–D6)

| Part | What | Main files |
|---|---|---|
| D1 | React + Vite + Tailwind + Zustand setup, login/register, protected routes | `src/api/client.ts`, `src/store/auth.ts`, `pages/LoginPage.tsx`, `RegisterPage.tsx`, `components/RequireAuth.tsx` |
| D2 | Repositories page: add by URL, scan, delete, live status polling | `store/repos.ts`, `components/RepoCard.tsx`, `AddRepoForm.tsx`, `ConfirmDialog.tsx`, `hooks.ts` |
| D3 | Risk report: summary cards, donut chart, quality panel, ranked table | `components/report/*` |
| D4 | Zoomable codebase heatmap (treemap) | `components/heatmap/*` |
| D5 | File detail page (SHAP charts, history, commits) + debt chart | `pages/FilePage.tsx`, `components/charts/*`, `metrics.ts` |
| D6 | Polish: error boundary, session-expired, offline banner, skeletons, accessibility, phone layout | `components/ErrorBoundary.tsx`, `AppLayout.tsx` |

### How the frontend talks to the backend
- `api/client.ts`: one function for every call — adds the JWT, turns FastAPI errors (incl. 422
  field lists and the 429 lockout) into readable messages, logs out on an expired token.
- In development Vite forwards `/api` to `127.0.0.1:8000` (no CORS needed).
- **Zustand stores**: `auth` (token + user, saved in localStorage; session-expired flag) and
  `repos` (list + add/scan/delete actions).
- **Polling**: while a scan is queued/running, refresh every 3 s (paused in background tabs).

### The screens
1. **Login / Register** — client-side checks with the same rules as the backend.
2. **Repositories** — "Add & scan", cards with status (Queued → Scanning… → Scanned / Failed +
   reason), risk bar, View report / Rescan / Delete (accessible confirm dialog).
3. **Risk report** — summary cards (files, need attention, expected bug-prone files), debt
   chart, donut (click to filter), code-quality averages graded on the tools' scales, ranked table
   (level chips, search, 6 sorts, paging, "Why?" with SHAP bars). Filters live in the URL.
4. **Codebase heatmap** — treemap: box size = lines (or commits), colour = risk (green → yellow
   10 % → orange 20 % → red 35 %+); click folder to zoom (animated), breadcrumb to zoom out,
   tooltips, file side panel.
5. **File page** — risk + rank, "What to do", two SHAP bar charts, risk-over-time chart with level
   bands, recent commits (bug fixes tagged), all measurements in 4 groups.

### How the heatmap works (be able to explain)
1. Build a folder tree from file paths (`tree.ts`), merging single-child folders (`src/flask`).
2. `d3-hierarchy`: sum each folder's size, sort, and run the **squarified treemap** layout to get
   rectangles that fill the box with near-square tiles.
3. Draw each file as an absolutely-positioned button coloured by risk; folders as labelled frames.
4. Zoom = re-run the layout with the clicked folder as root; CSS transitions animate the boxes.
5. Width measured immediately (`useLayoutEffect`) then followed with `ResizeObserver`.

### Performance and quality
- Code splitting: Recharts (~110 KB gzip) loads only on report/file pages; login + dashboard
  ~64 KB gzip.
- Error boundary per page (friendly screen, nav keeps working) + "new version available" for
  stale tabs; session-expired message and return to the original page; offline banner.
- Accessibility: skip link, page titles, keyboard-focusable tiles with spoken labels, aria
  attributes, reduced-motion support; every page checked at 375 px with no sideways scroll.

### Problems you solved
| Problem | Fix |
|---|---|
| First real sign-up failed (ECONNREFUSED ::1:8000) | Node resolves localhost to IPv6; proxy to `127.0.0.1` |
| Recharts tripled the bundle for every page | lazy-load report/file pages |
| Heatmap blank | ResizeObserver delayed in background tabs → measure in `useLayoutEffect` |
| Previous user's repos flashed after logout | clear repos store on logout |
| Ranking table cut off on phones ("Why?" hidden) | dot + % instead of badge, filename only, tighter columns |
| SHAP labels collided with values on phones | narrower labels, values placed outside bars |

### Viva questions
- **Q: Why Zustand and not Redux?** Small, no boilerplate, enough for two stores (auth, repos).
- **Q: How is the user kept logged in?** JWT in localStorage; checked once on load; an invalid
  token logs out and shows "session expired". (httpOnly cookies would be safer — future work.)
- **Q: How do you show live scan progress?** Polling every 3 s only while a scan is active.
- **Q: How does the treemap layout work?** d3-hierarchy squarified treemap (see above).
- **Q: Why put filters in the URL?** Shareable/bookmarkable views and browser back button work.
- **Q: How did you make it fast?** Code splitting and lazy routes.
- **Q: What happens if a page crashes?** Error boundary shows a friendly screen; the rest of the
  app keeps working.

---

# PART B — FULL TECHNICAL A–Z (for all members)

Everyone should be able to explain this part, not only their own chapter.

## B1. End-to-end: from a GitHub link to the dashboard

1. **User signs in** (React login page → `POST /api/auth/login` → JWT stored in the browser).
2. **User pastes a repo link** and clicks "Add & scan" → `POST /api/repositories` then
   `POST /api/repositories/{id}/scans` → backend returns **202 pending** immediately.
3. **Background scan job** (`backend/app/services/analysis.py`):
   1. `clone_repo` clones/updates the repo into `data/repos/` (Member 1),
   2. `load_commits` parses Git history (cached, only new commits),
   3. `add_message_features` adds NLP signals per commit (Member 2),
   4. `snapshot_features` = static metrics of today's code + history features → one row per file,
   5. `RiskPredictor.predict` → calibrated risk, level, rank, SHAP explanation, factors, advice,
   6. first scan only: 6 past snapshots scored for the trend charts,
   7. results + commit history saved in the database; scan → **completed**.
4. **Dashboard polls** every 3 s while the scan runs, then shows the card with risk counts.
5. **Report page** loads `/api/scans/{id}` (summary), `/files` (ranking), `/debt-forecast`
   (trend chart), and for the heatmap all files (in pages of 200).
6. **File page** loads one file's result, its history (`/file-history`) and recent commits.

## B2. Pull-request flow (GitHub App)

```
Developer opens PR -> GitHub -> POST /api/github/webhook (signed)
  -> verify HMAC, ignore re-deliveries, find repo -> create pull_request scan -> 202
  -> background: fetch refs/pull/N/head -> changed .py files (base...head)
     -> features + risk on PR head and on base -> Markdown table with up/down arrows
  -> App JWT (RS256) -> installation token -> create (or update) ONE PR comment
```

## B3. The features (what the model sees, ~43 numbers per file)

| Group | Features | Meaning |
|---|---|---|
| Size | loc, sloc, comments, comment_ratio, num_functions, num_classes, halstead_volume | how big the file is |
| Complexity | total/avg/max_complexity, max_nesting_depth, avg/max_function_length, max_params, maintainability | how hard the code is |
| Change activity | commit_count, churn, lines_added, lines_deleted, recent_commit_count, recent_churn, age_days, days_since_last_change | how often and how much it changes |
| Bug history | bug_fix_count, bug_fix_ratio | past bug fixes |
| Team | num_developers, top_author_share | how many people touch it, ownership |
| Coupling | fan_in, fan_out, coupling, instability, num_imports | dependencies |
| Tests | has_test_file, test_importers | proxy for testing |
| Duplication | duplication (%) | copy-pasted code |
| Commit messages | msg_frustrated, msg_rushed, msg_short, msg_revert, msg_words, msg_late_night, msg_weekend, msg_hf_frustration | NLP signals |

**Label**: `label_bug_prone` = 1 if the file gets at least one bug-fix commit in the 6 months
after the snapshot.

## B4. Algorithms explained simply

- **Bug-fix detection**: keyword rules on commit messages + exclusions (typo/docs/CI/lint) +
  ignore fix commits touching more than 10 files.
- **Rename tracking**: read history newest → oldest; when a rename old → new appears, remember
  "old = latest name of new"; every older row of the old path is counted under the latest name.
- **Cyclomatic complexity (McCabe)**: 1 + number of decision points (if, for, while, and, or,
  except…) in a function. 1–10 simple, 11–20 moderate, above 20 complex.
- **Maintainability index (Radon)**: formula of Halstead volume, complexity and lines, scaled
  0–100; 20+ easy (A), 10–19 moderate (B), below 10 hard (C).
- **Coupling**: build the internal import graph from the AST; fan-in = files importing me,
  fan-out = internal files I import.
- **Duplication**: normalise lines (strip spaces, drop blanks/comments/imports), hash every
  window of 6 lines; windows seen in 2+ places = duplicated lines.
- **Time-based snapshots**: features from the past of T, labels from T → T+6 months; no leakage.
- **Logistic regression**: score = weighted sum of (log-scaled, standardised) features;
  probability = 1 / (1 + e^(−score)). Class weights "balanced" to handle 14 % positives.
- **Random forest / XGBoost**: many decision trees (averaged / boosted) — more flexible, but
  XGBoost overfitted our small dataset.
- **ROC-AUC**: probability that a random bug-prone file is ranked above a random safe file
  (0.5 random, 1.0 perfect). **PR-AUC**: precision-recall area, honest under class imbalance.
- **Recall@20 %**: review the top 20 % of files → what share of future bug-prone files we catch.
- **Precision@5**: of the 5 files flagged first per repo snapshot, how many really got bugs.
- **Bootstrap 95 % interval**: resample whole repo snapshots 500 times, recompute the metric.
- **Platt calibration**: p = sigmoid(a × score + b), fitted on out-of-time predictions.
- **SHAP**: contribution of each feature to one prediction; contributions + base value = score.
- **Squarified treemap**: rectangles proportional to size, kept close to squares.
- **Debt projection**: straight line through the last 6 snapshots of "expected bug-prone files"
  (= sum of risks), extended 6/12/18 months, band = ±1.96 × spread of the past points.

## B5. Model results and honest findings

(Full table in A2.) Key messages for the faculty:
1. ROC-AUC 0.80; 63 % of bug-prone files found in the top 20 %; ~3× better than random at top 5.
2. Works on unseen repositories (0.79–0.86).
3. Tied with "biggest files first" — the known "size effect"; without size features we still get 0.80.
4. XGBoost overfitted and was rejected.
5. Measured per line of code reviewed (effort-aware), no method beats random → future work.
6. Calibrated probabilities make Critical/High/Medium/Low meaningful.

## B6. Database
Five tables: `users`, `repositories`, `scans`, `file_analyses`, `commit_history` (details in A3).
Development: SQLite file `backend/risk_predictor.db`, created automatically.
Production: PostgreSQL, schema managed by Alembic (`backend/migrations/`).

## B7. API reference

| Method | Path | Purpose |
|---|---|---|
| GET | /api/health | health check |
| POST | /api/auth/register | create account |
| POST | /api/auth/login | get JWT (form fields: username = email, password) |
| GET | /api/auth/me | current user |
| POST | /api/repositories | add repo by URL |
| GET | /api/repositories | list my repos (+ latest scan, risk counts) |
| GET / DELETE | /api/repositories/{id} | one repo / delete it |
| POST | /api/repositories/{id}/scans | start a scan (202) |
| GET | /api/repositories/{id}/scans | scan history |
| GET | /api/repositories/{id}/trends | risk per scan |
| GET | /api/repositories/{id}/debt-forecast | debt history + projection |
| GET | /api/repositories/{id}/file-history?path= | one file across scans + commits |
| GET | /api/scans/{id} | scan summary (counts, averages) |
| GET | /api/scans/{id}/files | ranked files (risk_level, q, sort, limit, offset) |
| GET | /api/scans/{id}/files/{file_id} | one file in detail |
| POST | /api/github/webhook | GitHub App events |

Interactive docs (Swagger): http://localhost:8000/docs

## B8. Security checklist
bcrypt passwords · JWT 24 h · login lockout (5 failures / 5 min) · same error for wrong password
and unknown user · 404 for other users' data · HMAC-verified webhooks, refused without a secret ·
25 MB payload limit · hidden 500 errors with request IDs · production refuses unsafe settings ·
non-root Docker user · secrets only via environment variables (`.env` is git-ignored).

## B9. Testing
- `python -m pytest` → **52 tests, ~30–60 s, fully offline**.
- A synthetic Git repo (60 dated commits, 3 authors, bug fixes, late-night commits, a rename and
  a PR branch) is built in a temp folder; the real pipeline, model and API run on it.
- Pipeline 23 · Model 8 · Backend 21 (auth, data isolation, scan job, webhook, errors,
  non-Python repo).
- Manual browser tests for every frontend part (desktop and phone width).

## B10. Deployment
- Local: two terminals (backend with uvicorn, frontend with `npm run dev`).
- Docker: `docker compose up --build` (API + PostgreSQL).
- Cloud: Render Blueprint (`render.yaml`) or AWS (App Runner/ECS + RDS + EFS).
- Needs ~1.5–2 GB RAM with the emotion model; set `RISK_USE_HF=0` on small servers.

## B11. How to run (local)

Terminal 1 (backend):
```
cd backend
..\venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
Terminal 2 (frontend):
```
cd frontend
npm run dev
```
Open http://localhost:5173 · test login `manager@example.com` / `testpass123`.

Useful: `python -m pytest` (tests) · `python -m pipeline.run refresh` (update data) ·
`python -m ml.train` then `python -m ml.package` (retrain the model).

## B12. Glossary A–Z

- **A** — **Alembic**: database migration tool. **AUC**: ranking quality (0.5 random, 1 perfect). **AST**: Abstract Syntax Tree, the parsed form of code.
- **B** — **bcrypt**: slow password-hashing algorithm. **Bug-fix commit**: commit whose message shows it fixed a bug. **Brier score**: mean squared error of probabilities.
- **C** — **Calibration**: predicted probabilities match real frequencies. **Churn**: lines added + deleted. **Coupling**: fan-in + fan-out. **CORS**: browser rule for cross-site requests.
- **D** — **Data leakage**: future information sneaking into training. **Duplication**: share of copy-pasted code. **Docker**: container packaging.
- **E** — **Effort-aware evaluation**: results per line of code reviewed. **Expected bug-prone files**: sum of calibrated risks.
- **F** — **FastAPI**: Python web framework. **Fan-in / fan-out**: who imports me / whom I import. **Feature**: one input number for the model.
- **G** — **GitPython**: Python library for Git. **GitHub App**: app account that receives webhooks and comments on PRs.
- **H** — **Halstead volume**: size measure from operators/operands. **HMAC**: keyed hash used to sign webhooks. **HuggingFace**: hub of pretrained NLP models.
- **I** — **Imputation**: filling missing values (median). **Installation token**: short-lived GitHub token for one App installation.
- **J** — **JWT**: JSON Web Token, the signed login token.
- **K** — **KLOC**: thousand lines of code (risk-weighted KLOC = sum of risk × lines / 1000).
- **L** — **Label**: the answer the model learns (bug-prone or not). **Lizard**: complexity analyser. **Logistic regression**: linear model that outputs probabilities.
- **M** — **Maintainability index**: 0–100 ease-of-change score. **McCabe**: inventor of cyclomatic complexity. **Migration**: scripted database schema change.
- **N** — **NLP**: natural language processing (here: commit messages). **Nesting depth**: deepest stack of if/for/while blocks.
- **O** — **Overfitting**: model memorises training data (XGBoost 0.98 train vs 0.74 test). **Out-of-time validation**: validate only on later years.
- **P** — **Platt scaling**: logistic calibration. **Precision@5**: hits among the top 5. **PR-AUC**: precision-recall area. **PostgreSQL**: production database.
- **Q** — **Query parameters**: filters in the URL (`?level=high&sort=loc`).
- **R** — **Radon**: Python code-metrics tool. **Random forest**: many averaged decision trees. **Recall@20 %**: share of bug-prone files in the top 20 %. **React**: UI library.
- **S** — **SHAP**: per-feature explanation of a prediction. **Snapshot**: the repo at a date T. **SQLAlchemy**: Python ORM (database layer). **SZZ**: research method linking fixes to bugs. **Squarified treemap**: heatmap layout.
- **T** — **Time-based split**: train on the past, test on the future. **Treemap**: nested rectangles chart. **Tailwind**: CSS utility framework.
- **U** — **Uvicorn**: server that runs FastAPI. **Unseen-repo test**: leave-one-repo-out evaluation.
- **V** — **Vendored code**: third-party code copied into a repo (skipped). **Vite**: frontend build tool.
- **W** — **Webhook**: HTTP call GitHub makes to us on events (PR opened, push).
- **X** — **XGBoost**: gradient-boosted trees (rejected: overfitting).
- **Y** — **YAML**: config format of `docker-compose.yml` and `render.yaml`.
- **Z** — **Zustand**: small React state-management library.

---

# PART C — SUMMARY FOR ALL MEMBERS

## C1. The project in one minute (anyone can say this)

> "Technical debt builds up silently, and teams find risky files only after they cause bugs.
> We built an AI platform that predicts which Python files of a GitHub repository are likely to
> need bug fixes in the next 6 months. Member 1 extracts the Git history and code metrics of every
> file. Member 2 adds NLP on commit messages and trains a calibrated machine-learning model, with
> SHAP explaining each prediction. Member 3 built the FastAPI backend, database, background scans
> and a GitHub App that comments on pull requests. Member 4 built the React dashboard with a risk
> ranking, a zoomable heatmap and a projected technical-debt chart. Trained on 3,051 file
> snapshots from 4 real projects and tested on the future, it reaches ROC-AUC 0.80 and finds 63 %
> of future bug-prone files in the top 20 %."

## C2. Each member in three lines

**Member 1 — Data Engineer**
- Built the pipeline that clones a repo and turns its Git history (following renames, detecting
  bug fixes) and source code (AST, Radon, Lizard, coupling, duplication) into ~43 numbers per file.
- Built the leak-free time-based dataset (3,051 rows, 95 snapshots, 4 repos) and the automated,
  cached refresh (4.5 min → 40 s).
- Key words: churn, cyclomatic complexity, rename tracking, snapshots, no leakage.

**Member 2 — ML & AI Scientist**
- Added commit-message NLP (incl. a HuggingFace emotion model) and compared baselines, logistic
  regression, random forest, XGBoost with a time-based split → logistic regression, AUC 0.80.
- Calibrated the scores (error 0.30 → 0.02), set data-driven risk levels, explained every file with
  exact SHAP values and advice, and built the debt projection.
- Key words: AUC, recall@20 %, overfitting, calibration, SHAP.

**Member 3 — Backend & Integrations Architect**
- Built the FastAPI REST API (auth, repos, scans, ranking, trends, debt forecast), the 5-table
  database and security (bcrypt, JWT, lockout, data isolation).
- Built background scan jobs and the GitHub App (signed webhooks → PR review → one auto-updated
  PR comment), Docker/PostgreSQL/Render deployment and 52 automated tests.
- Key words: REST, JWT, webhook, HMAC, background job, Alembic, Docker.

**Member 4 — Frontend & Data Viz Engineer**
- Built the React + TypeScript dashboard: login, repositories with live scan status, risk report
  with donut chart and ranked table, file pages with SHAP charts.
- Built the zoomable codebase heatmap (d3 treemap) and the "Projected Technical Debt Over Time"
  chart; made it fast (code splitting), robust (error screens) and mobile-friendly.
- Key words: React, Zustand, Recharts, treemap, polling, code splitting.

## C3. Key numbers (whole team)

| What | Number |
|---|---|
| Training repos | 4 (requests, flask, click, httpx) |
| Dataset | 3,051 rows · 95 snapshots · 14.4 % bug-prone |
| Features per file | ~43 (size, complexity, history, team, coupling, tests, duplication, NLP) |
| Train / test | 2,168 rows (before 2023) / 764 rows (2023+) |
| Test ROC-AUC | 0.80 (95 % range 0.77–0.83) |
| Bug-prone files caught in top 20 % | 63 % |
| Precision of top 5 | 0.38 (random 0.13) |
| Unseen repository AUC | 0.79–0.86 |
| Calibration error | 0.30 → 0.02 |
| Risk levels | Critical ≥ 0.35 · High 0.20 · Medium 0.10 · Low below |
| Automated tests | 52 |
| Flask demo | 35 files: 1 critical (app.py, 35 %), 3 high, 4 medium, 27 low; 2.5 expected bug-prone files |

## C4. Honest limitations and future work
1. **Python only** — JS/TS needs a parser (e.g. esprima), new training data and retraining.
2. **Small dataset** (4 repos) — more repositories would make the model stronger.
3. **Bug-fix labels are keyword-based** — some real fixes are missed, some non-fixes counted;
   linking to GitHub issues would be better.
4. **Ties with "biggest files first"**; effort-aware results (per line) are weak.
5. **Test coverage not measured** — we use "has a test file" as a proxy.
6. **Debt projection** is a straight-line trend: only ~7 % better than "same as last time".
7. **Scaling**: background jobs run inside the server; a job queue (RQ/Celery) would handle many users.
8. **Login token in localStorage**; httpOnly cookies would be safer.
9. Docker image and Render deployment written but not yet built/deployed; GitHub App needs to be
   registered on a GitHub account.

## C5. Demo script for the faculty (~10 minutes)

| Time | Who | What to show |
|---|---|---|
| 0:00 | Anyone | One-minute pitch (C1) + pipeline diagram (Part 0.3) |
| 1:00 | Member 4 | Log in → Repositories → paste `https://github.com/pallets/click` → **Add & scan** → card goes Queued → Scanning… → Scanned (talk while it runs) |
| 2:30 | Member 1 | While scanning: explain what happens — cloning, Git history, renames, bug-fix detection, static metrics; show `data/processed/dataset.csv` |
| 4:00 | Member 4 | Open **flask** report: summary cards, debt chart, donut (click Critical), ranked table, **Why?** |
| 5:00 | Member 2 | Explain the `app.py` score: SHAP factors (Size +1.09, Change activity +0.66…), calibration, levels; show the model comparison table (A2) and the honest "size effect" |
| 6:30 | Member 4 | **Codebase heatmap**: zoom into `sansio/`, switch to "Number of commits", click a file → full page (history, commits) |
| 7:30 | Member 3 | `http://localhost:8000/docs` (API), explain the database, JWT security, the PR-comment flow (B2) with the sample PR comment; run `python -m pytest` (52 tests) |
| 9:00 | Anyone | Limitations and future work (C4), questions |

Tips: start both servers and log in **before** the demo; flask is already scanned in the test
account; scanning a new repo takes 1–2 minutes the first time; use Python repos only.

## C6. Common viva questions (whole team should know)

1. **What problem does it solve?** Predicts which files will need bug fixes in the next 6 months,
   explains why and what to do, so teams fix technical debt before it hurts.
2. **Where did the data come from?** We built it ourselves from the Git history and code of 4
   public Python repos: 3,051 file snapshots labelled by bug fixes in the following 6 months.
3. **How is a file labelled "bug-prone"?** At least one bug-fix commit in the 6 months after the
   snapshot date.
4. **Which model and why?** Logistic regression: tied best on validation, least overfitting,
   explainable; XGBoost overfitted.
5. **How good is it?** ROC-AUC 0.80 on future data, 63 % of risky files in the top 20 %, 3× random
   at the top 5, works on unseen repos.
6. **How do you explain predictions?** SHAP values per feature, grouped into factors, plus advice.
7. **What does the risk score mean?** A calibrated probability of a bug fix in 6 months.
8. **How does the GitHub integration work?** Signed webhook on PR → background review of changed
   files → one PR comment, updated on later pushes.
9. **How is it secured?** bcrypt, JWT, lockout, per-user data isolation, signed webhooks.
10. **How did you test it?** 52 automated tests on a synthetic repo + manual browser tests;
    PostgreSQL tested; time-based model evaluation.
11. **What would you improve?** More languages and repos, issue-linked labels, coverage, job queue.
12. **What was the hardest part?** Clean Git data (renames, broken dates, bulk commits),
    avoiding data leakage, and the GitHub App flow.

## C7. Study plan for each member
1. Read **Part 0** and your own chapter in Part A until you can explain it without notes.
2. Open your files in VS Code and find each function mentioned in your chapter.
3. Read the other three chapters once, then **Part B** (everyone must know B1, B2, B5).
4. Run the project (B11) and practise your part of the demo (C5).
5. Ask each other the viva questions (your chapter + C6).
