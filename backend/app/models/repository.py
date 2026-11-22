from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class Repository(Base):
    """A GitHub repository a user has connected (via the GitHub App)."""

    __tablename__ = "repositories"
    # Two different users may analyse the same public repo, but one user can't add it twice.
    __table_args__ = (UniqueConstraint("owner_id", "full_name", name="uq_owner_repo"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # Indexed because webhooks (Part 6) look repos up by "owner/repo".
    full_name: Mapped[str] = mapped_column(String(255), index=True)
    url: Mapped[str] = mapped_column(String(500))  # the GitHub URL the user submitted
    language: Mapped[str | None] = mapped_column(String(50), default="Python")
    # Set when the GitHub App is installed; needed to post PR comments (Part 6).
    installation_id: Mapped[int | None] = mapped_column(BigInteger)
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    owner: Mapped["User"] = relationship(back_populates="repositories")  # noqa: F821
    scans: Mapped[list["Scan"]] = relationship(  # noqa: F821
        back_populates="repository", cascade="all, delete-orphan"
    )
    commits: Mapped[list["CommitHistory"]] = relationship(  # noqa: F821
        back_populates="repository", cascade="all, delete-orphan"
    )
