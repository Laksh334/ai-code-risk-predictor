# Architecture

AI-Powered Code Complexity & Technical Debt Predictor: how the system is built and why.
The diagrams are Mermaid (GitHub renders them as pictures; in VS Code use a Mermaid preview).

## 1. System context

Who and what the system talks to.

```mermaid
flowchart LR
    manager([Engineering manager<br/>browser])
    dev([Developer<br/>opens a pull request])
    subgraph product[Code Risk Predictor - one web service]
        app[React dashboard<br/>+ FastAPI API]
    end
    gh[(GitHub<br/>public repos, PRs)]
    db[(PostgreSQL)]
    hf[(HuggingFace hub<br/>emotion model, downloaded once)]

    manager -- "HTTPS: sign in, add repo, read reports" --> app
    app -- "git clone / fetch" --> gh
    dev -- "opens / updates PR" --> gh
    gh -- "signed webhook" --> app
    app -- "PR comment (GitHub App)" --> gh
    app <--> db
    app -. first scan .-> hf
```

## 2. Components (the four members' parts)

```mermaid
flowchart TB
    subgraph M4[Member 4 - frontend/ React + TypeScript]
        ui[Pages: login, repositories, report,<br/>heatmap, file page]
        stores[Zustand stores: auth, repos]
        client[api/client.ts]
        ui --> stores --> client
    end
    subgraph M3[Member 3 - backend/ FastAPI]
        routes[REST routes: auth, repositories,<br/>scans, github webhook]
        jobs[Background jobs:<br/>run_scan, run_pr_scan]
        ghapp[GitHub App client<br/>JWT, installation token, comments]
        orm[SQLAlchemy models + Alembic]
        routes --> jobs
        jobs --> ghapp
        routes --> orm
        jobs --> orm
    end
    subgraph M1[Member 1 - pipeline/]
        scanner[scanner.scan_repository]
        hist[git_history: commits, renames,<br/>bug fixes, history features]
        static[static_analysis: ast, Radon,<br/>Lizard, coupling, duplication]
        store[store: commit + static caches]
        scanner --> hist & static & store
    end
    subgraph M2[Member 2 - ml/]
        nlp[nlp: commit-message signals]
        pred[predictor: calibrated model]
        expl[explain: SHAP, factors, advice]
        fc[forecast: debt projection]
        pred --> expl
    end
    client -- "JSON over HTTPS /api" --> routes
    jobs --> scanner
    scanner --> nlp
    jobs --> pred
    routes --> fc
```

## 3. Scan flow (user adds a repository)

```mermaid
sequenceDiagram
    actor U as User (browser)
    participant API as FastAPI
    participant J as Background job
    participant P as pipeline (Member 1)
    participant M as ml (Member 2)
    participant DB as Database
    U->>API: POST /api/repositories {url}
    U->>API: POST /api/repositories/{id}/scans
    API->>DB: scan = pending
    API-->>U: 202 pending (instant)
    API->>J: run_scan(scan_id)
    J->>P: scan_repository(url)
    P->>P: clone/pull, parse new commits (cache), static metrics
    P->>M: add_message_features(commits)
    P-->>J: features per file (+ past snapshots on first scan)
    J->>M: RiskPredictor.predict(features)
    M-->>J: risk, level, rank, SHAP, factors, advice
    J->>DB: file results, commit history, scan = completed
    loop every 3 s while running
        U->>API: GET /api/repositories
    end
    U->>API: GET /api/scans/{id}, /files, /debt-forecast
```

## 4. Pull-request flow (GitHub App)

```mermaid
sequenceDiagram
    actor D as Developer
    participant GH as GitHub
    participant W as /api/github/webhook
    participant J as run_pr_scan
    participant P as pipeline + ml
    D->>GH: open / push to PR
    GH->>W: pull_request event (X-Hub-Signature-256)
    W->>W: verify HMAC, ignore re-delivery, find repo
    W-->>GH: 202 (within 10 s)
    W->>J: background job
    J->>P: fetch refs/pull/N/head, changed .py files
    J->>P: risk on PR head and on base branch
    J->>GH: App JWT (RS256) -> installation token
    J->>GH: create comment (first run) / update same comment (later pushes)
```

## 5. Data model

```mermaid
erDiagram
    USERS ||--o{ REPOSITORIES : owns
    REPOSITORIES ||--o{ SCANS : has
    REPOSITORIES ||--o{ COMMIT_HISTORY : has
    SCANS ||--o{ FILE_ANALYSES : contains
    USERS {
        int id PK
        string email
        string hashed_password
        string github_username
    }
    REPOSITORIES {
        int id PK
        int owner_id FK
        string full_name
        string url
        bigint installation_id
    }
    SCANS {
        int id PK
        int repository_id FK
        string trigger
        string status
        string commit_sha
        int pr_number
        float overall_risk
        string model_version
        text report_markdown
    }
    FILE_ANALYSES {
        int id PK
        int scan_id FK
        string file_path
        float risk_score
        string risk_level
        int priority_rank
        json metrics
        json explanation
        json factors
        text recommendation
    }
    COMMIT_HISTORY {
        int id PK
        int repository_id FK
        string commit_sha
        datetime commit_date
        string file_path
        int lines_added
        int lines_deleted
        bool is_bug_fix
    }
```

`scans.trigger`: `manual`, `push` (default branch), `pull_request` (PR review, kept out of the
repo's trends), `history` (past snapshots computed on the first scan for the trend charts).

## 6. ML lifecycle (offline vs online)

```mermaid
flowchart LR
    repos[pipeline/repos.txt<br/>requests, flask, click, httpx] --> ds[pipeline.run dataset<br/>3,051 time-based rows]
    ds --> train[ml.train<br/>time split, tuning, compare]
    train --> pkg[ml.package<br/>Platt calibration, thresholds,<br/>refit on all data]
    pkg --> model[(data/models/<br/>production.joblib, 78 KB)]
    model --> online[Backend scans and PR reviews<br/>RiskPredictor.predict]
```

Offline (run by us, minutes): build the dataset, train, calibrate, save one model file.
Online (every scan, seconds): load the model once, score today's features, explain.

## 7. Deployment

```mermaid
flowchart LR
    user([Browser]) -- HTTPS --> svc
    subgraph render[Render or any Docker host]
        svc[Docker container<br/>uvicorn: FastAPI + built React app<br/>non-root, health check /api/health]
        disk[(/data volume<br/>clones, caches, emotion model)]
        pg[(PostgreSQL)]
        svc --- disk
        svc --- pg
    end
    svc <-- git, webhooks, comments --> github[(GitHub)]
```

Image build: stage 1 builds the React app with Node; stage 2 is Python 3.13 slim + git +
CPU-only PyTorch, with the built dashboard and the trained model copied in. On start the
entrypoint waits for the database and runs `alembic upgrade head`.

## 8. Key design decisions

| Decision | Why | Trade-off |
|---|---|---|
| Time-based snapshots for training data | Labels come from the future of each snapshot, like real use; no leakage | Recent snapshots can't be labelled yet (dropped) |
| Logistic regression over XGBoost | Tied best on validation, least overfitting, exact and simple SHAP | Less flexible on bigger data |
| Platt calibration + data-driven levels | Scores become real probabilities; levels match real outcomes | Needs out-of-time predictions |
| SHAP grouped into factors | Exact (SHAP adds up) and readable; hides confusing signs of overlapping features | Less detail (detail still shown per metric) |
| Background tasks inside the API process | Simple, no extra infrastructure | Many users would need a job queue (RQ/Celery) |
| Dashboard served by the API server | One service, one URL, no CORS, one deploy | Frontend and backend scale together |
| Caches for commits and static metrics | Refresh 4.5 min → 40 s; past code never changes | Cache invalidation (versioned, force-push aware) |
| 404 for other users' data | Doesn't reveal that a resource exists | – |
| Signed webhooks, fail closed | Only GitHub can trigger PR reviews | Needs the secret configured |
| Pinned ML library versions | A pickled model must load with the versions it was trained with | Upgrades require retraining |

## 9. Repository layout

```
pipeline/   data extraction (Member 1)       ml/        ML, NLP, SHAP (Member 2)
backend/    API, DB, GitHub App (Member 3)   frontend/  React dashboard (Member 4)
tests/      52 automated tests               docs/      this file, deployment, demo, study guide
data/models/production.joblib                trained model (other data/ folders are generated)
Dockerfile, docker-compose.yml, render.yaml, docker/entrypoint.sh, backend/migrations/
```
