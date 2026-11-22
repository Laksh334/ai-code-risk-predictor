import enum

from sqlalchemy import JSON, Enum, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class RiskLevel(str, enum.Enum):
    """The four categories required by the project spec."""

    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class FileAnalysis(Base):
    """Risk result for one file inside one scan.

    Combines the three pipeline stages for that file:
      * Git-history features (Member 1's extraction)
      * Static-analysis metrics (Radon / Lizard)
      * ML prediction + SHAP explanation (Member 2's model)
    """

    __tablename__ = "file_analyses"
    # Dashboard query: "riskiest files of this scan" -> scan_id + risk_score.
    __table_args__ = (Index("ix_file_analyses_scan_risk", "scan_id", "risk_score"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_id: Mapped[int] = mapped_column(ForeignKey("scans.id", ondelete="CASCADE"))
    file_path: Mapped[str] = mapped_column(String(500), index=True)

    # --- ML prediction -------------------------------------------------------
    risk_score: Mapped[float] = mapped_column(Float)  # 0.0 (safe) .. 1.0 (risky)
    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel))
    # 1 = fix first. Lets the dashboard show the prioritised risk report directly.
    priority_rank: Mapped[int | None] = mapped_column(Integer)

    # --- Git-history features ------------------------------------------------
    commit_count: Mapped[int | None] = mapped_column(Integer)  # commit frequency
    churn: Mapped[int | None] = mapped_column(Integer)  # lines added + deleted
    num_developers: Mapped[int | None] = mapped_column(Integer)  # distinct authors
    bug_fix_count: Mapped[int | None] = mapped_column(Integer)  # bug-fix commits touching file

    # --- Static-analysis metrics (Radon / Lizard) ----------------------------
    complexity: Mapped[float | None] = mapped_column(Float)  # cyclomatic complexity
    loc: Mapped[int | None] = mapped_column(Integer)  # lines of code
    coupling: Mapped[float | None] = mapped_column(Float)
    duplication: Mapped[float | None] = mapped_column(Float)  # % duplicated lines
    test_coverage: Mapped[float | None] = mapped_column(Float)  # % covered
    maintainability: Mapped[float | None] = mapped_column(Float)  # Radon MI, 0..100

    # Any extra metrics, so a new scanner field doesn't need a schema change.
    metrics: Mapped[dict | None] = mapped_column(JSON)

    # --- Explainability (SHAP) -----------------------------------------------
    # e.g. [{"feature": "churn", "value": 3000, "impact": 0.21}, ...] sorted by |impact|
    explanation: Mapped[list | None] = mapped_column(JSON)
    # SHAP summed per factor: [{"factor": "size", "label": "Size", "impact": 0.98}, ...]
    factors: Mapped[list | None] = mapped_column(JSON)
    recommendation: Mapped[str | None] = mapped_column(Text)  # actionable advice

    scan: Mapped["Scan"] = relationship(back_populates="files")  # noqa: F821
