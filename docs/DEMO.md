# Demo script (≈ 10 minutes, 4 presenters)

Goal: show the faculty a working product, then show each member's part and understanding.
Background for answers: `docs/Team_Study_Guide.md` (viva questions per member, Part C6).

## Before the demo (15 minutes earlier)

- [ ] Laptop charged, internet on (a new scan clones from GitHub).
- [ ] VS Code open on `ai-code-risk-predictor3`, two terminals running:
      backend `cd backend` → `..\venv\Scripts\python -m uvicorn app.main:app --port 8000`
      frontend `cd frontend` → `npm run dev`
- [ ] Browser tab 1: http://localhost:5173, **signed in** as `manager@example.com` / `testpass123`
      (flask is already scanned there).
- [ ] Browser tab 2: http://localhost:8000/docs (API).
- [ ] Browser tab 3: `docs/ARCHITECTURE.md` on GitHub, or the pipeline diagram from the study guide.
- [ ] Terminal 3 ready in the project folder for `.\venv\Scripts\python -m pytest`.
- [ ] Do one practice run of the whole script.

## The script

| Time | Presenter | Do | Say (key points) |
|---|---|---|---|
| 0:00 | Any | Show the architecture diagram | Problem: technical debt hides until it causes bugs. Solution: predict which files need bug fixes in the next 6 months, explain why, recommend what to do. Four parts: data → model → backend → dashboard. |
| 1:00 | Member 4 | Repositories page → paste `https://github.com/pallets/click` → **Add & scan** | "The scan runs in the background; the card updates by itself." (Queued → Scanning…) |
| 1:30 | Member 1 | Talk while it scans (no clicks) | "We clone the repo, read every commit (following renames, detecting bug-fix commits), and measure every file's code: complexity, size, nesting, coupling, duplication. For training we took snapshots every 6 months of 4 real projects: features from the past, labels from the next 6 months, so nothing leaks from the future. 3,051 rows." |
| 3:00 | Member 4 | Card shows **Scanned** with counts → open the **flask** report | Summary cards, "Projected technical debt over time" (solid = measured, dashed = projection), donut: click **Critical**, ranked table, **Why?** on `app.py`. |
| 4:30 | Member 2 | On `app.py` → **Full details** (file page) | "35 % = calibrated probability of a bug fix in 6 months. SHAP shows why: size +1.09, change activity +0.66, coupling +0.52; duplication pulls it down. Logistic regression, tested on 2023+ data it never saw: ROC-AUC 0.80, 63 % of risky files in the top 20 %, 3× random at the top 5. XGBoost overfitted. Honest finding: ties with 'biggest files first' — a known effect." |
| 6:00 | Member 4 | **Codebase heatmap** tab → zoom into `sansio/` → toggle **Number of commits** → hover / click a tile | "Each box is a file: size = lines (or commits), colour = risk. Big red = where technical debt concentrates." |
| 7:00 | Member 3 | Tab 2 (`/docs`) → show endpoints; explain PR flow; run `pytest` in terminal 3 | "FastAPI with JWT login, bcrypt, per-user data isolation. A GitHub App receives signed webhooks when a PR opens, reviews the changed files and posts one comment that updates on later pushes. Docker + PostgreSQL + Render config. 52 automated tests." (show `52 passed`) |
| 8:30 | Any | Limitations and future work | Python only; 4 training repos; keyword-based bug labels; coverage not measured; job queue for many users. |
| 9:00 | All | Questions | Answer from your own chapter; pass to the member who owns the part. |

## If something goes wrong

| Problem | What to do |
|---|---|
| No internet / new scan fails | Skip the click scan; use the already-scanned **flask** repo for everything. |
| A scan of a non-Python repo fails | Expected: "No Python source files found…" — explain the model is Python-only. |
| Port already in use (WinError 10013) | Another server is running; close it or use `--port 8001`. |
| Backend error after editing `pipeline/` or `ml/` | Restart the backend terminal (`Ctrl+C`, run again). |
| Logged out ("session expired") | Sign in again; you return to the page you were on. |
| Login locked (too many wrong passwords) | Wait the shown seconds, or register a new account. |
| Tests slow | They take ~30–60 s; start them a little earlier. |

## Sample PR comment (to show if there's no GitHub App set up)

> **3 Python file(s) changed** — 2 high · 1 medium
>
> | File | Risk | Change vs base | Main factors |
> |---|---|---|---|
> | `src/flask/cli.py` | **0.25** High | ≈ same (was 0.25) | Size +0.93, Coupling +0.40 |
> | `src/flask/helpers.py` | **0.21** High | ≈ same (was 0.21) | Size +0.82, Coupling +0.40 |
> | `src/flask/sessions.py` | **0.14** Medium | ≈ same (was 0.14) | Size +0.67, Coupling +0.27 |

(Real output for flask PR #6168, produced in our tests.)
