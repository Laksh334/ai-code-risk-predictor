# Deployment guide

The whole product (React dashboard + API + pipeline + model) is **one Docker image** and runs
as **one web service** with a PostgreSQL database. Three ways to run it:

| Option | For | Needs |
|---|---|---|
| A. Local, two terminals | development, the faculty demo | Python venv + Node (already set up) |
| B. Docker Compose | "production-like" on your laptop | Docker Desktop |
| C. Render (cloud) | a public URL | GitHub account + Render account (paid plan for enough RAM/disk) |

---

## A. Local (two terminals)

```powershell
cd backend
..\venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
```
```powershell
cd frontend
npm run dev
```
Open http://localhost:5173. Restart the backend after changing files in `pipeline/` or `ml/`
(`--reload` only watches `backend/`).

**Single-server variant** (what production does): build the dashboard once, let the API serve it.
```powershell
cd frontend; npm run build; cd ..\backend
$env:FRONTEND_DIST = "..\frontend\dist"; ..\venv\Scripts\python -m uvicorn app.main:app --port 8000
```
Open http://localhost:8000 (dashboard) and http://localhost:8000/docs (API).

---

## B. Docker Compose (app + PostgreSQL)

1. Install Docker Desktop.
2. In the project folder: `copy .env.example .env`, then set `SECRET_KEY` in `.env`:
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`
3. Start:
   ```powershell
   docker compose up --build
   ```
4. Open http://localhost:8000. The first build takes several minutes (it installs PyTorch and
   builds the dashboard); later starts are fast. Data stays in Docker volumes.

What happens on start: the container waits for PostgreSQL, runs `alembic upgrade head`
(creates/updates the tables), then starts the server. With `ENVIRONMENT=production` it refuses
to start if `SECRET_KEY` is weak or the database is SQLite.

---

## C. Render (public URL)

1. **Push the project to GitHub** (see README / git commands below).
2. Render dashboard → **New → Blueprint** → connect your GitHub → pick the repository.
   Render reads `render.yaml` and proposes:
   - web service `code-risk-predictor` (Docker, health check `/api/health`, 10 GB disk),
   - PostgreSQL `code-risk-db` (its URL is wired into `DATABASE_URL` automatically),
   - a generated `SECRET_KEY`.
3. Click **Apply**. The first build takes ~10 minutes.
4. Open `https://code-risk-predictor.onrender.com` (your exact URL is shown by Render),
   create an account and add a Python repository.

**Plans and memory.** With the AI emotion model the app needs ~1.5–2 GB RAM (`plan: standard`).
To save money use a 512 MB plan and set `RISK_USE_HF=0` (the emotion signal is then left
unknown and the model fills it in). Persistent disks need a paid plan; without one, repositories
are re-cloned after each deploy (slower first scans, nothing else breaks).

**Optional: automatic PR comments.** Create a GitHub App (README section "GitHub App"), set its
webhook URL to `https://<your-render-url>/api/github/webhook`, and add `GITHUB_WEBHOOK_SECRET`,
`GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY` in the Render service's Environment tab. PR comments link
to the dashboard automatically (Render's URL is used unless `DASHBOARD_URL` is set).

---

## The code on GitHub

The project is on GitHub at **https://github.com/Laksh334/ai-code-risk-predictor** (branch `main`).
Render deploys from that repository. After changing something:
```powershell
git add .
git commit -m "Describe the change"
git push
```
Render rebuilds automatically on every push to `main` (Blueprint auto-deploy).

Starting from scratch on another computer:
```powershell
git clone https://github.com/Laksh334/ai-code-risk-predictor.git
```
then set up the venv and `npm install` as in the README (the trained model is in the repo).

---

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | SQLite file | PostgreSQL URL in production (`postgres://` is converted automatically) |
| `SECRET_KEY` | dev value | signs login tokens; must be long and random in production |
| `ENVIRONMENT` | development | `production` turns on safety checks |
| `AUTO_CREATE_TABLES` | true | false in production: Alembic manages the schema |
| `FRONTEND_DIST` | (empty) | folder of the built dashboard; set in the Docker image |
| `CORS_ORIGINS` | localhost:5173 | only needed if the dashboard runs on another URL |
| `DASHBOARD_URL` | Render URL / localhost:5173 | link used in PR comments |
| `RISK_DATA_DIR` | `./data` | clones and caches (Docker: `/data` volume) |
| `RISK_MODEL_PATH` | `data/models/production.joblib` | trained model |
| `RISK_USE_HF` | 1 | 0 = skip the ~1 GB emotion model |
| `HISTORY_POINTS` | 6 | past snapshots computed on a repo's first scan |
| `GITHUB_WEBHOOK_SECRET`, `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY(_PATH)`, `GITHUB_TOKEN` | – | GitHub App / PR comments |

---

## Status (honest)

- Tested: local run, single-server mode, migrations and a full scan on real PostgreSQL 17.9,
  52 automated tests.
- Written but **not yet run here**: the Docker image build and the Render deployment (Docker isn't
  installed on the development laptop, and Render needs your account). Expect to fix small issues
  on the first real build; the build log will point to them.
