import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ScanTrigger(str, enum.Enum):
    manual = "manual"
    pull_request = "pull_request"
    push = "push"
    # Past snapshot computed during a repo's first scan, so the trend chart isn't empty.
    history = "history"


# Scans of the default branch. PR scans only cover the PR's changed files, so they are kept
# out of the repo's trends / debt forecast / "latest scan".
BRANCH_TRIGGERS = (ScanTrigger.manual, ScanTrigger.push, ScanTrigger.history)
LATEST_TRIGGERS = (ScanTrigger.manual, ScanTrigger.push)


class ScanStatus(str, enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class Scan(Base):
    """One risk-analysis run over a repository (e.g. triggered by a PR webhook)."""

    __tablename__ = "scans"
    __table_args__ = (Index("ix_scans_repo_created", "repository_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"), index=True
    )
    trigger: Mapped[ScanTrigger] = mapped_column(Enum(ScanTrigger), default=ScanTrigger.manual)
    status: Mapped[ScanStatus] = mapped_column(Enum(ScanStatus), default=ScanStatus.pending)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    pr_number: Mapped[int | None] = mapped_column()
    # ID of the comment we posted on GitHub, so later pushes can update it instead of spamming.
    github_comment_id: Mapped[int | None] = mapped_column(BigInteger)
    # The PR report as Markdown (also kept when no GitHub credentials are configured).
    report_markdown: Mapped[str | None] = mapped_column(Text)
    overall_risk: Mapped[float | None] = mapped_column(Float)  # 0.0 (safe) .. 1.0 (risky)
    # Which trained model produced the predictions, so old scans stay comparable.
    model_version: Mapped[str | None] = mapped_column(String(50))
    error_message: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped["Repository"] = relationship(back_populates="scans")  # noqa: F821
    files: Mapped[list["FileAnalysis"]] = relationship(  # noqa: F821
        back_populates="scan", cascade="all, delete-orphan"
    )
