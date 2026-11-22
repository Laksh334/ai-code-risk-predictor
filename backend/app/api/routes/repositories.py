from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, OwnedRepo
from app.models import FileAnalysis, Repository, RiskLevel, Scan, ScanStatus
from app.models.scan import LATEST_TRIGGERS
from app.schemas.dashboard import RepositoryCreate, RepositoryOut, ScanOut
from app.services.github_url import parse_github_url

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _with_latest_scan(repo: Repository, latest: Scan | None, summary: dict | None = None) -> RepositoryOut:
    out = RepositoryOut.model_validate(repo)
    out.latest_scan = ScanOut.model_validate(latest) if latest else None
    if summary:
        out.report_scan_id, out.risk_counts = summary["scan_id"], summary["counts"]
    return out


def _report_summaries(db, repo_ids: list[int]) -> dict[int, dict]:
    """Files per risk level from each repo's latest COMPLETED scan, so a card can show the last
    report's numbers even while a new scan is running. Two queries for any number of repos."""
    scan_ids = dict(db.execute(
        select(Scan.repository_id, func.max(Scan.id))
        .where(Scan.repository_id.in_(repo_ids), Scan.status == ScanStatus.completed,
               Scan.trigger.in_(LATEST_TRIGGERS))
        .group_by(Scan.repository_id)
    ).all())
    if not scan_ids:
        return {}
    counts: dict[int, dict] = {sid: {lv: 0 for lv in RiskLevel} for sid in scan_ids.values()}
    for sid, level, n in db.execute(
        select(FileAnalysis.scan_id, FileAnalysis.risk_level, func.count())
        .where(FileAnalysis.scan_id.in_(scan_ids.values()))
        .group_by(FileAnalysis.scan_id, FileAnalysis.risk_level)
    ):
        counts[sid][level] = n
    return {rid: {"scan_id": sid, "counts": counts[sid]} for rid, sid in scan_ids.items()}


@router.post("", response_model=RepositoryOut, status_code=status.HTTP_201_CREATED)
def add_repository(body: RepositoryCreate, db: DbSession, user: CurrentUser) -> RepositoryOut:
    """Submit a GitHub repository URL to analyse."""
    parsed = parse_github_url(body.url)
    if parsed is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Not a valid GitHub repository URL (expected https://github.com/<owner>/<repo>)",
        )
    owner, name = parsed
    full_name = f"{owner}/{name}"
    exists = db.scalar(
        select(Repository).where(
            Repository.owner_id == user.id, func.lower(Repository.full_name) == full_name.lower()
        )
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "You already added this repository")

    repo = Repository(owner_id=user.id, full_name=full_name, url=f"https://github.com/{full_name}")
    db.add(repo)
    db.commit()
    db.refresh(repo)
    return _with_latest_scan(repo, None)


@router.get("", response_model=list[RepositoryOut])
def list_repositories(db: DbSession, user: CurrentUser) -> list[RepositoryOut]:
    """All of the user's repos, each with its most recent scan (for the dashboard home)."""
    repos = db.scalars(
        select(Repository).where(Repository.owner_id == user.id).order_by(Repository.created_at.desc())
    ).all()
    if not repos:
        return []

    # One query for every repo's latest scan instead of one query per repo.
    latest_ids = (
        select(func.max(Scan.id))
        .where(Scan.repository_id.in_([r.id for r in repos]), Scan.trigger.in_(LATEST_TRIGGERS))
        .group_by(Scan.repository_id)
    )
    latest = {s.repository_id: s for s in db.scalars(select(Scan).where(Scan.id.in_(latest_ids)))}
    summaries = _report_summaries(db, [r.id for r in repos])
    return [_with_latest_scan(r, latest.get(r.id), summaries.get(r.id)) for r in repos]


@router.get("/{repo_id}", response_model=RepositoryOut)
def get_repository(repo: OwnedRepo, db: DbSession) -> RepositoryOut:
    latest = db.scalar(
        select(Scan)
        .where(Scan.repository_id == repo.id, Scan.trigger.in_(LATEST_TRIGGERS))
        .order_by(Scan.id.desc())
        .limit(1)
    )
    return _with_latest_scan(repo, latest, _report_summaries(db, [repo.id]).get(repo.id))


@router.delete("/{repo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_repository(repo: OwnedRepo, db: DbSession) -> Response:
    """Deletes the repo and all its scans, results and history."""
    db.delete(repo)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
