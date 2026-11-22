# Backend & Integrations (Member 3)

Part of the AI-Powered Code Complexity & Technical Debt Predictor (see the root `README.md`).

This folder is the "engine room": REST APIs for the dashboard (Member 4), the database, and
the GitHub App integration. When a PR is opened, a webhook triggers Member 1's scanner
and Member 2's model, then posts the risk report as a PR comment.

Stack: Python FastAPI · SQLAlchemy · PostgreSQL (SQLite for local dev) · GitHub Webhooks · Docker · Render/AWS

## Run

From the project root (one shared venv for all Python modules):

```powershell
.\venv\Scripts\Activate.ps1
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs for interactive API docs.

## Roadmap (built in parts)

- [x] **Part 1** — Project skeleton, config, CORS, `GET /api/health`
- [x] **Part 2** — Database schema (SQLAlchemy models): users, repositories, scans, file analyses, commit history
- [x] **Part 3** — User accounts & security: register/login, password hashing, JWT auth
- [x] **Part 4** — Dashboard REST APIs for Member 4: repos, scans, risky files, history/trends
- [ ] **Part 5** — Integration layer: adapters for Member 1's scanner and Member 2's model (stubs until theirs are ready)
- [ ] **Part 6** — GitHub App webhooks: verify signature → catch "PR opened" → scan → predict → post PR comment
- [ ] **Part 7** — Docker + docker-compose (API + PostgreSQL) + Render/AWS deploy config
- [ ] **Part 8** — Tests (pytest), error handling, final API docs for the frontend team

## Database schema (Part 2)

| Table | Purpose | Key columns |
|---|---|---|
| `users` | Accounts | `email` (unique), `hashed_password`, `github_username` |
| `repositories` | Repos a user submitted / connected | `owner_id → users`, `full_name` (unique per user), `url`, `language`, `installation_id` |
| `scans` | One risk analysis run (manual, PR, or push) | `repository_id`, `trigger`, `status`, `commit_sha`, `pr_number`, `overall_risk`, `model_version` |
| `file_analyses` | Per-file result of a scan | prediction: `risk_score`, `risk_level` (critical/high/medium/low), `priority_rank` · git: `commit_count`, `churn`, `num_developers`, `bug_fix_count` · static: `complexity`, `loc`, `coupling`, `duplication`, `test_coverage`, `maintainability` · SHAP: `explanation` (JSON), `recommendation` |
| `commit_history` | Mined git history (same columns as Member 1's CSV) | `repository_id`, `commit_sha`, `file_path`, `author`, `lines_added/deleted`, `is_bug_fix` |

Indexes are on the columns the dashboard filters by (`repository_id + file_path`,
`scan_id + risk_score`, `commit_date`) so queries stay fast with millions of history rows.
Local dev uses SQLite (`risk_predictor.db`); set `DATABASE_URL` to a PostgreSQL URL in production.

## Auth API (Part 3) — for the frontend

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/auth/register` | JSON `{email, password (8+ chars), github_username?}` | user (201) · 409 if email taken |
| POST | `/api/auth/login` | **form** fields `username` (= email), `password` | `{access_token, token_type: "bearer"}` · 401 if wrong |
| GET | `/api/auth/me` | header `Authorization: Bearer <token>` | current user · 401 if missing/expired |

Passwords are hashed with bcrypt; tokens are JWTs valid for 24h. Set `SECRET_KEY` in `.env` before deploying.

## Dashboard API (Part 4) — for the frontend

Every route below needs `Authorization: Bearer <token>`. Users only ever see their own data
(someone else's repo/scan returns 404).

| Method | Path | What it's for |
|---|---|---|
| POST | `/api/repositories` | Submit `{url: "https://github.com/owner/repo"}` · 422 bad URL · 409 already added |
| GET | `/api/repositories` | Dashboard home: all repos, each with `latest_scan` |
| GET | `/api/repositories/{id}` | One repo + latest scan |
| DELETE | `/api/repositories/{id}` | Remove repo and all its data (204) |
| POST | `/api/repositories/{id}/scans` | Start an analysis → 202 `pending` · 409 if one is running |
| GET | `/api/repositories/{id}/scans?limit&offset` | Scan history (paginated) |
| GET | `/api/repositories/{id}/trends?last=30` | Risk over time + files per level per scan (Recharts line/area) |
| GET | `/api/repositories/{id}/file-history?path=...` | One file's risk across scans + recent commits |
| GET | `/api/scans/{id}` | Status, `risk_counts` per level (pie chart), quality `averages` |
| GET | `/api/scans/{id}/files` | **Prioritised risk ranking** · filters `risk_level`, `q` (path search) · `sort` = `priority` (default) / `risk_score` / `complexity` / `churn` / `bug_fix_count` / `num_developers` / `loc` · `limit`, `offset` |
| GET | `/api/scans/{id}/files/{file_id}` | File detail: all metrics, SHAP `explanation`, `recommendation` |

Paginated responses look like `{items: [...], total, limit, offset}`.
Starting a scan only queues it for now; Part 5 connects the real scanner + model.

### Demo data (build the frontend before the pipeline is ready)

```powershell
python -m app.seed_demo
```

Creates the test login `demo@example.com` / `demo-password` with the `psf/requests` repo:
4 completed monthly scans (risk rising over time), 16 files with metrics, SHAP explanations,
recommendations and commit history. Re-running resets the demo data. Local dev only.
