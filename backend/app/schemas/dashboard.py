"""Response shapes for the dashboard APIs (what Member 4's React app receives)."""

from datetime import datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.models import RiskLevel, ScanStatus, ScanTrigger

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Paginated list: use `total` to render page numbers."""

    items: list[T]
    total: int
    limit: int
    offset: int


# --- Repositories --------------------------------------------------------------


class RepositoryCreate(BaseModel):
    url: str = Field(max_length=500, examples=["https://github.com/psf/requests"])


class ScanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    repository_id: int
    trigger: ScanTrigger
    status: ScanStatus
    commit_sha: str | None
    pr_number: int | None
    overall_risk: float | None
    model_version: str | None
    error_message: str | None
    created_at: datetime
    finished_at: datetime | None
    report_markdown: str | None = None  # PR scans: the comment posted on GitHub


class RepositoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    url: str
    language: str | None
    default_branch: str
    created_at: datetime
    latest_scan: ScanOut | None = None
    # From the latest completed scan (may differ from latest_scan while a new one runs):
    report_scan_id: int | None = None
    risk_counts: dict[RiskLevel, int] | None = None


# --- Scan results ------------------------------------------------------------


class QualityAverages(BaseModel):
    """Code-quality insights: averages over all files of a scan."""

    complexity: float | None
    maintainability: float | None
    test_coverage: float | None
    duplication: float | None


class ScanDetail(ScanOut):
    total_files: int
    risk_counts: dict[RiskLevel, int]  # e.g. {"critical": 3, "high": 10, ...} -> pie chart
    averages: QualityAverages


class ExplanationItem(BaseModel):
    """One SHAP factor: positive impact pushes risk up, negative pulls it down."""

    feature: str
    label: str | None = None  # readable name, e.g. "Most complex function"
    group: str | None = None  # factor it belongs to, e.g. "complexity"
    value: float | int | str | None = None
    impact: float


class FactorItem(BaseModel):
    """SHAP impacts summed per factor (Size, Complexity, Change activity, ...)."""

    factor: str
    label: str
    impact: float


class FileAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_id: int
    file_path: str
    risk_score: float
    risk_level: RiskLevel
    priority_rank: int | None
    commit_count: int | None
    churn: int | None
    num_developers: int | None
    bug_fix_count: int | None
    complexity: float | None
    loc: int | None
    coupling: float | None
    duplication: float | None
    test_coverage: float | None
    maintainability: float | None
    explanation: list[ExplanationItem] | None
    factors: list[FactorItem] | None = None
    recommendation: str | None
    metrics: dict | None = None  # every other measured feature (nesting depth, fan-in, ...)


# --- Trends & history --------------------------------------------------------


class DebtPoint(BaseModel):
    date: datetime
    files: int | None = None
    expected_bug_prone_files: float
    risk_weighted_kloc: float
    critical: int | None = None
    high: int | None = None
    medium: int | None = None
    low: int | None = None
    # projection only: 95% band
    expected_bug_prone_files_low: float | None = None
    expected_bug_prone_files_high: float | None = None
    risk_weighted_kloc_low: float | None = None
    risk_weighted_kloc_high: float | None = None


class DebtTrend(BaseModel):
    per_year: float
    direction: str  # rising / falling / flat


class DebtForecast(BaseModel):
    """'Projected Technical Debt Over Time': history from scans + straight-line projection."""

    history: list[DebtPoint]
    projection: list[DebtPoint]
    trend: dict[str, DebtTrend]


class TrendPoint(BaseModel):
    """One completed scan on the repo's risk-over-time chart."""

    scan_id: int
    created_at: datetime
    overall_risk: float | None
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0


class FileHistoryPoint(BaseModel):
    scan_id: int
    created_at: datetime
    risk_score: float
    risk_level: RiskLevel


class CommitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    commit_sha: str
    commit_date: datetime
    author: str | None
    change_type: str | None
    lines_added: int
    lines_deleted: int
    commit_message: str | None
    is_bug_fix: bool


class FileHistory(BaseModel):
    file_path: str
    risk_over_time: list[FileHistoryPoint]
    recent_commits: list[CommitOut]
