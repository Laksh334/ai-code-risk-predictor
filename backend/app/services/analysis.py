"""C1 - The scan job: runs Member 1's pipeline and Member 2's model, stores the results.

    POST /api/repositories/{id}/scans  -> creates a `pending` scan and schedules run_scan()
    run_scan(scan_id)                  -> running -> completed (or failed with error_message)

Runs as a FastAPI background task (in a worker thread) so the request returns at once.
A production setup with many users would move this to a job queue (e.g. RQ/Celery).
"""

from __future__ import annotations

import logging
import math
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import delete, insert, select, update

from app.config import settings
from app.db.session import SessionLocal
from app.models import CommitHistory, FileAnalysis, RiskLevel, Scan, ScanStatus, ScanTrigger
from app.models.scan import BRANCH_TRIGGERS

# The pipeline/ and ml/ packages live in the project root, one level above backend/.
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

log = logging.getLogger(__name__)

# Features that have their own DB column; everything else numeric goes into `metrics`.
COLUMN_FEATURES = {
    "commit_count": "commit_count", "churn": "churn", "num_developers": "num_developers",
    "bug_fix_count": "bug_fix_count", "max_complexity": "complexity", "loc": "loc",
    "coupling": "coupling", "duplication": "duplication", "maintainability": "maintainability",
}
INT_COLUMNS = {"commit_count", "churn", "num_developers", "bug_fix_count", "loc"}


@lru_cache(maxsize=1)
def get_predictor():
    from ml.predictor import RiskPredictor  # heavy import: only when the first scan runs

    return RiskPredictor.load()


def _num(v):
    """JSON/DB-safe number: NaN/inf -> None, numpy -> python."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return int(f) if f.is_integer() else round(f, 4)


def _file_rows(features, predictions, scan_id: int, with_details: bool) -> list[dict]:
    preds = predictions.set_index(predictions.index)
    rows = []
    for idx, feat in features.iterrows():
        p = preds.loc[idx]
        row = {
            "scan_id": scan_id,
            "file_path": feat["file_path"],
            "risk_score": float(p["risk_score"]),
            "risk_level": RiskLevel(p["risk_level"]),
            "priority_rank": int(p["priority_rank"]),
            "test_coverage": None,  # not measured; `has_test_file`/`test_importers` are in metrics
            "metrics": {k: _num(v) for k, v in feat.items()
                        if k not in COLUMN_FEATURES and k != "file_path" and _num(v) is not None},
        }
        for feature, column in COLUMN_FEATURES.items():
            v = _num(feat.get(feature))
            row[column] = int(v) if v is not None and column in INT_COLUMNS else v
        if with_details:
            row["explanation"] = p["explanation"]
            row["factors"] = p["factors"]
            row["recommendation"] = p["recommendation"]
        rows.append(row)
    return rows


def _store_commits(db, repo_id: int, commits) -> None:
    """Replace the repo's commit history (file names can change after renames)."""
    db.execute(delete(CommitHistory).where(CommitHistory.repository_id == repo_id))
    if commits.empty:
        return
    cols = ["commit_sha", "commit_date", "author", "file_path", "change_type",
            "lines_added", "lines_deleted", "commit_message", "is_bug_fix"]
    records = commits[cols].assign(repository_id=repo_id)
    records["commit_date"] = records["commit_date"].dt.to_pydatetime()
    data = records.to_dict("records")
    for i in range(0, len(data), 2000):
        db.execute(insert(CommitHistory), data[i : i + 2000])


def describe_error(exc: Exception) -> str:
    """Message stored on a failed scan and shown in the dashboard. Problems the user can act on
    (missing/private repo, no Python files) get the plain sentence; anything unexpected keeps the
    error type, which helps debugging."""
    from pipeline.errors import PipelineUserError

    text = str(exc) if isinstance(exc, PipelineUserError) else f"{type(exc).__name__}: {exc}"
    return text[:1000]


def run_scan(scan_id: int) -> None:
    """Background job. Never raises: failures are stored on the scan."""
    with SessionLocal() as db:
        scan = db.get(Scan, scan_id)
        if scan is None:
            return
        repo = scan.repository
        scan.status = ScanStatus.running
        db.commit()
        try:
            from pipeline.scanner import scan_repository

            predictor = get_predictor()
            # First real scan of this repo -> also compute past snapshots for the trend chart.
            has_history = db.scalar(select(Scan.id).where(
                Scan.repository_id == repo.id, Scan.status == ScanStatus.completed,
                Scan.trigger.in_(BRANCH_TRIGGERS)).limit(1))
            result = scan_repository(repo.url, history_points=0 if has_history else settings.history_points)

            preds = predictor.predict(result.features)
            db.execute(insert(FileAnalysis), _file_rows(result.features, preds, scan.id, with_details=True))
            scan.commit_sha = result.commit_sha
            scan.model_version = predictor.version
            scan.overall_risk = round(float(preds["risk_score"].mean()), 4) if len(preds) else None

            for snap in result.history:
                hist = Scan(repository_id=repo.id, trigger=ScanTrigger.history, status=ScanStatus.completed,
                            commit_sha=snap.commit_sha, model_version=predictor.version,
                            created_at=snap.date, finished_at=datetime.now(timezone.utc))
                db.add(hist)
                db.flush()
                hp = predictor.predict(snap.features, explain=False)  # trend only: no SHAP needed
                hist.overall_risk = round(float(hp["risk_score"].mean()), 4) if len(hp) else None
                db.execute(insert(FileAnalysis), _file_rows(snap.features, hp, hist.id, with_details=False))

            _store_commits(db, repo.id, result.commits)
            scan.status = ScanStatus.completed
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()
            log.info("Scan %s of %s completed: %d files, %d history points",
                     scan.id, repo.full_name, len(preds), len(result.history))
        except Exception as exc:  # store the reason so the dashboard can show it
            db.rollback()
            log.exception("Scan %s of %s failed", scan_id, repo.full_name)
            scan = db.get(Scan, scan_id)
            scan.status = ScanStatus.failed
            scan.error_message = describe_error(exc)
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()


def fail_interrupted_scans() -> None:
    """On startup: scans left pending/running by a crash or restart can never finish."""
    with SessionLocal() as db:
        n = db.execute(
            update(Scan)
            .where(Scan.status.in_([ScanStatus.pending, ScanStatus.running]))
            .values(status=ScanStatus.failed, error_message="Interrupted by a server restart",
                    finished_at=datetime.now(timezone.utc))
        ).rowcount
        db.commit()
        if n:
            log.warning("Marked %d interrupted scan(s) as failed", n)
