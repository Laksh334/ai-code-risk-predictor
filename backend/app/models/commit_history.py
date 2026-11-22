from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class CommitHistory(Base):
    """One file change in one commit. Columns match Member 1's mined CSV
    (commit_sha, commit_date, author, file, change_type, lines_added, lines_deleted, commit_message).
    This is the biggest table (millions of rows), so it is indexed for per-file lookups."""

    __tablename__ = "commit_history"
    __table_args__ = (
        # Re-importing the same history must not create duplicates.
        UniqueConstraint("repository_id", "commit_sha", "file_path", name="uq_commit_file"),
        Index("ix_commit_history_repo_file", "repository_id", "file_path"),
        Index("ix_commit_history_repo_date", "repository_id", "commit_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("repositories.id", ondelete="CASCADE"))
    commit_sha: Mapped[str] = mapped_column(String(40))
    commit_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    author: Mapped[str | None] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    change_type: Mapped[str | None] = mapped_column(String(20))  # ADD / MODIFY / DELETE / RENAME
    lines_added: Mapped[int] = mapped_column(Integer, default=0)
    lines_deleted: Mapped[int] = mapped_column(Integer, default=0)
    commit_message: Mapped[str | None] = mapped_column(Text)
    # True when the commit is identified as a bug fix (e.g. "fix", "bug", "issue #" in message).
    # Bug-fix frequency is a key feature and the label for the ML model.
    is_bug_fix: Mapped[bool] = mapped_column(Boolean, default=False)

    repository: Mapped["Repository"] = relationship(back_populates="commits")  # noqa: F821
