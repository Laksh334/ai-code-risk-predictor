"""A4 - The scanner: one call from a GitHub URL to model-ready features of today's code.

This is what the backend (C1) and the GitHub webhook (C2) call:

    from pipeline.scanner import scan_repository
    result = scan_repository("https://github.com/psf/requests", history_points=6)
    result.features   # one row per source file, same feature columns as the training data
    result.history    # optional past snapshots (every 6 months) -> instant trend chart
    result.commits    # the commits table (who/when/what, bug fix?, message signals)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from git import Repo

from ml.nlp import add_message_features
from pipeline.dataset import snapshot_features
from pipeline.errors import NoSourceFiles
from pipeline.git_history import clone_repo
from pipeline.static_analysis import resolve_rev
from pipeline.store import DEFAULT_CACHE, load_commits

_DROP = ("first_commit", "last_commit", "commit_sha")


@dataclass
class Snapshot:
    date: datetime
    commit_sha: str
    features: pd.DataFrame


@dataclass
class ScanResult:
    repo: str  # folder name, e.g. "psf__requests"
    commit_sha: str  # exact code version that was analysed
    scanned_at: datetime
    features: pd.DataFrame  # one row per source file
    commits: pd.DataFrame = field(default_factory=pd.DataFrame)
    history: list[Snapshot] = field(default_factory=list)

    @property
    def summary(self) -> dict:
        f = self.features
        return {
            "repo": self.repo,
            "commit_sha": self.commit_sha,
            "scanned_at": self.scanned_at.isoformat(),
            "files": len(f),
            "unparseable_files": int((~f["parse_ok"]).sum()) if len(f) else 0,
            "history_points": len(self.history),
        }


def fetch_pull_request(source: str, number: int) -> tuple[Path, str]:
    """Make sure a PR's commits are in the local clone. Returns (repo path, PR head sha).
    GitHub exposes every PR (also from forks) as refs/pull/<n>/head."""
    from pipeline.git_history import _NO_PROMPT

    repo_path = clone_repo(source)
    repo = Repo(repo_path)
    with repo.git.custom_environment(**_NO_PROMPT):
        repo.git.fetch("origin", f"+refs/pull/{number}/head:refs/remotes/origin/pr/{number}")
    return repo_path, repo.commit(f"origin/pr/{number}").hexsha


def changed_source_files(repo_path: Path, base: str, head: str) -> list[str]:
    """Python source files the PR adds or modifies (compared with where it branched off)."""
    from pipeline.filters import is_source_file

    out = Repo(repo_path).git.diff("--name-only", "--diff-filter=AMR", f"{base}...{head}")
    return [p for p in out.splitlines() if is_source_file(p)]


def _no_source_message(repo: Repo, sha: str) -> str:
    """'No Python files ... it mostly contains .tsx (64), .ts (9) files.'"""
    from collections import Counter

    exts = Counter(
        p.rsplit(".", 1)[-1].lower() for p in repo.git.ls_tree("-r", "--name-only", sha).splitlines()
        if "." in p.rsplit("/", 1)[-1]
    )
    for ignore in ("json", "md", "txt", "png", "jpg", "svg", "lock", "yml", "yaml", "gitignore", "ico"):
        exts.pop(ignore, None)
    top = ", ".join(f".{e} ({n})" for e, n in exts.most_common(3))
    found = f" It mostly contains {top} files." if top else ""
    return ("No Python source files found in this repository, so there is nothing to score: the risk model "
            f"currently analyses Python code only.{found}")


def _clean(df: pd.DataFrame, include_tests: bool) -> pd.DataFrame:
    if not df.empty and not include_tests:
        df = df[~df["is_test_file"]]
    return df.drop(columns=[c for c in _DROP if c in df.columns]).reset_index(drop=True)


def scan_repository(
    source: str,
    rev: str = "HEAD",
    include_tests: bool = False,
    history_points: int = 0,
    history_interval_months: int = 6,
    cache_dir: str | Path = DEFAULT_CACHE,
) -> ScanResult:
    """Clone/update the repo, refresh its commit cache, and compute every file's features.

    `history_points` > 0 also computes features as they were 6, 12, 18... months ago
    (skipping dates before the first commit), oldest first."""
    repo_path = clone_repo(source)
    repo = Repo(repo_path)
    commits = add_message_features(load_commits(repo_path, cache_dir=cache_dir))
    sha = repo.commit(rev).hexsha
    now = pd.Timestamp(datetime.now(timezone.utc))
    features = _clean(snapshot_features(repo_path, commits, now, rev=sha), include_tests)
    if features.empty:
        raise NoSourceFiles(_no_source_message(repo, sha))

    history: list[Snapshot] = []
    if history_points and not commits.empty:
        first = commits["commit_date"].min()
        for k in range(history_points, 0, -1):
            when = (now - pd.DateOffset(months=history_interval_months * k)).normalize()
            if when <= first:
                continue
            snap = _clean(snapshot_features(repo_path, commits, when), include_tests)
            if not snap.empty:
                history.append(Snapshot(when.to_pydatetime(), resolve_rev(repo, when.strftime("%Y-%m-%d")), snap))

    return ScanResult(
        repo=repo_path.resolve().name,
        commit_sha=sha,
        scanned_at=now.to_pydatetime(),
        features=features,
        commits=commits,
        history=history,
    )
