from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from sqlalchemy import func, select

from app.api.deps import DbSession, OwnedRepo, OwnedScan
from app.models import CommitHistory, FileAnalysis, RiskLevel, Scan, ScanStatus, ScanTrigger
from app.models.scan import BRANCH_TRIGGERS
from app.schemas.dashboard import (
    CommitOut,
    DebtForecast,
    DebtPoint,
    FileAnalysisOut,
    FileHistory,
    FileHistoryPoint,
    Page,
    QualityAverages,
    ScanDetail,
    ScanOut,
    TrendPoint,
)

from app.services.analysis import run_scan  # noqa: E402  (also puts pipeline/ml on sys.path)

router = APIRouter(tags=["scans"])

SortField = Literal[
    "priority", "risk_score", "complexity", "churn", "bug_fix_count", "num_developers", "loc"
]


# --- Scans of a repository ------------------------------------------------------


@router.post(
    "/repositories/{repo_id}/scans",
    response_model=ScanOut,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_scan(repo: OwnedRepo, db: DbSession, background: BackgroundTasks) -> Scan:
    """Queue a new analysis. Returns immediately with status `pending`; the scan runs in the
    background (clone -> metrics -> model -> SHAP). Poll GET /scans/{id} until it is
    `completed` or `failed` (then `error_message` says why). A repo's first scan also
    computes past snapshots, so the trend charts have data straight away."""
    active = db.scalar(
        select(Scan.id).where(
            Scan.repository_id == repo.id,
            Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
        )
    )
    if active:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Scan {active} is already in progress")
    scan = Scan(repository_id=repo.id, trigger=ScanTrigger.manual, status=ScanStatus.pending)
    db.add(scan)
    db.commit()
    db.refresh(scan)
    background.add_task(run_scan, scan.id)
    return scan


@router.get("/repositories/{repo_id}/scans", response_model=Page[ScanOut])
def list_scans(
    repo: OwnedRepo,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[ScanOut]:
    """Scans that were run (manual / PR / push), newest first. Back-filled history snapshots
    are left out here; they show up in /trends and /debt-forecast."""
    base = select(Scan).where(Scan.repository_id == repo.id, Scan.trigger != ScanTrigger.history)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    scans = db.scalars(base.order_by(Scan.id.desc()).limit(limit).offset(offset)).all()
    return Page(items=scans, total=total, limit=limit, offset=offset)


@router.get("/repositories/{repo_id}/trends", response_model=list[TrendPoint])
def repository_trends(
    repo: OwnedRepo,
    db: DbSession,
    last: Annotated[int, Query(ge=1, le=200, description="Number of recent scans")] = 30,
) -> list[TrendPoint]:
    """Historical trend: overall risk and files per risk level for each completed scan,
    oldest first (ready for a Recharts line/area chart)."""
    scans = db.scalars(
        select(Scan)
        .where(Scan.repository_id == repo.id, Scan.status == ScanStatus.completed,
            Scan.trigger.in_(BRANCH_TRIGGERS))
        .order_by(Scan.created_at.desc())  # by date: back-filled snapshots have later ids
        .limit(last)
    ).all()[::-1]
    if not scans:
        return []

    points = {s.id: TrendPoint(scan_id=s.id, created_at=s.created_at, overall_risk=s.overall_risk) for s in scans}
    counts = db.execute(
        select(FileAnalysis.scan_id, FileAnalysis.risk_level, func.count())
        .where(FileAnalysis.scan_id.in_(points))
        .group_by(FileAnalysis.scan_id, FileAnalysis.risk_level)
    )
    for scan_id, level, n in counts:
        setattr(points[scan_id], level.value, n)
    return list(points.values())


@router.get("/repositories/{repo_id}/file-history", response_model=FileHistory)
def file_history(
    repo: OwnedRepo,
    db: DbSession,
    path: Annotated[str, Query(description="File path, e.g. src/requests/models.py")],
    commits: Annotated[int, Query(ge=0, le=200)] = 20,
) -> FileHistory:
    """How one file's risk changed across scans, plus its recent commits."""
    rows = db.execute(
        select(Scan.id, Scan.created_at, FileAnalysis.risk_score, FileAnalysis.risk_level)
        .join(FileAnalysis, FileAnalysis.scan_id == Scan.id)
        .where(
            Scan.repository_id == repo.id,
            Scan.status == ScanStatus.completed,
            Scan.trigger.in_(BRANCH_TRIGGERS),
            FileAnalysis.file_path == path,
        )
        .order_by(Scan.created_at)
    ).all()
    recent = db.scalars(
        select(CommitHistory)
        .where(CommitHistory.repository_id == repo.id, CommitHistory.file_path == path)
        .order_by(CommitHistory.commit_date.desc())
        .limit(commits)
    ).all()
    if not rows and not recent:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No data for this file")
    return FileHistory(
        file_path=path,
        risk_over_time=[
            FileHistoryPoint(scan_id=i, created_at=t, risk_score=s, risk_level=l) for i, t, s, l in rows
        ],
        recent_commits=[CommitOut.model_validate(c) for c in recent],
    )


@router.get("/repositories/{repo_id}/debt-forecast", response_model=DebtForecast)
def debt_forecast(repo: OwnedRepo, db: DbSession) -> DebtForecast:
    """Technical debt per completed scan (expected bug-prone files = sum of risk scores;
    risk-weighted KLOC = sum of risk x size) and a straight-line projection 6/12/18 months
    ahead with a 95% band (Member 2's ml/forecast.py)."""
    import pandas as pd

    from ml.forecast import project

    rows = db.execute(
        select(Scan.created_at, FileAnalysis.risk_score, FileAnalysis.risk_level, FileAnalysis.loc)
        .join(FileAnalysis, FileAnalysis.scan_id == Scan.id)
        .where(Scan.repository_id == repo.id, Scan.status == ScanStatus.completed,
            Scan.trigger.in_(BRANCH_TRIGGERS))
    ).all()
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No completed scans yet")
    df = pd.DataFrame(rows, columns=["date", "risk", "level", "loc"])
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df["level"] = df["level"].map(lambda lv: lv.value)
    df["weighted"] = df["risk"] * df["loc"].fillna(0)
    g = df.groupby("date")
    history = pd.DataFrame({
        "files": g.size(),
        "expected_bug_prone_files": g["risk"].sum().round(2),
        "risk_weighted_kloc": (g["weighted"].sum() / 1000).round(2),
    })
    levels = df.pivot_table(index="date", columns="level", values="risk", aggfunc="size", fill_value=0)
    for lv in RiskLevel:
        history[lv.value] = levels.get(lv.value, 0)
    history = history.reset_index()
    projection, trend = project(history)
    to_points = lambda d: [DebtPoint(**r) for r in d.to_dict("records")]
    return DebtForecast(history=to_points(history), projection=to_points(projection), trend=trend)


# --- One scan --------------------------------------------------------------------


@router.get("/scans/{scan_id}", response_model=ScanDetail)
def get_scan(scan: OwnedScan, db: DbSession) -> ScanDetail:
    """Scan status + summary: files per risk level and code-quality averages."""
    counts = dict(
        db.execute(
            select(FileAnalysis.risk_level, func.count())
            .where(FileAnalysis.scan_id == scan.id)
            .group_by(FileAnalysis.risk_level)
        ).all()
    )
    avg = db.execute(
        select(
            func.avg(FileAnalysis.complexity),
            func.avg(FileAnalysis.maintainability),
            func.avg(FileAnalysis.test_coverage),
            func.avg(FileAnalysis.duplication),
        ).where(FileAnalysis.scan_id == scan.id)
    ).one()

    def r(x: float | None) -> float | None:
        return round(x, 2) if x is not None else None

    return ScanDetail(
        **ScanOut.model_validate(scan).model_dump(),
        total_files=sum(counts.values()),
        risk_counts={level: counts.get(level, 0) for level in RiskLevel},
        averages=QualityAverages(
            complexity=r(avg[0]), maintainability=r(avg[1]), test_coverage=r(avg[2]), duplication=r(avg[3])
        ),
    )


@router.get("/scans/{scan_id}/files", response_model=Page[FileAnalysisOut])
def list_scan_files(
    scan: OwnedScan,
    db: DbSession,
    risk_level: RiskLevel | None = None,
    q: Annotated[str | None, Query(max_length=200, description="Filter by path substring")] = None,
    sort: SortField = "priority",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[FileAnalysisOut]:
    """The prioritised risk ranking. Default order: priority rank, then highest risk first."""
    base = select(FileAnalysis).where(FileAnalysis.scan_id == scan.id)
    if risk_level:
        base = base.where(FileAnalysis.risk_level == risk_level)
    if q:
        base = base.where(FileAnalysis.file_path.ilike(f"%{q}%"))

    if sort == "priority":
        order = [FileAnalysis.priority_rank.asc().nulls_last(), FileAnalysis.risk_score.desc()]
    else:
        order = [getattr(FileAnalysis, sort).desc().nulls_last()]

    total = db.scalar(select(func.count()).select_from(base.subquery()))
    files = db.scalars(base.order_by(*order, FileAnalysis.id).limit(limit).offset(offset)).all()
    return Page(items=files, total=total, limit=limit, offset=offset)


@router.get("/scans/{scan_id}/files/{file_id}", response_model=FileAnalysisOut)
def get_scan_file(scan: OwnedScan, file_id: int, db: DbSession) -> FileAnalysis:
    """One file's full detail: metrics, SHAP explanation and recommendation."""
    f = db.get(FileAnalysis, file_id)
    if f is None or f.scan_id != scan.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found in this scan")
    return f
