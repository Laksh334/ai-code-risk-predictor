"""Importing this package registers every table on Base.metadata."""

from app.models.commit_history import CommitHistory
from app.models.file_analysis import FileAnalysis, RiskLevel
from app.models.repository import Repository
from app.models.scan import Scan, ScanStatus, ScanTrigger
from app.models.user import User

__all__ = [
    "CommitHistory",
    "FileAnalysis",
    "Repository",
    "RiskLevel",
    "Scan",
    "ScanStatus",
    "ScanTrigger",
    "User",
]
