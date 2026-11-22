"""A1 - Clone a GitHub repo and turn its Git history into clean tables.

Two outputs:
  * commits table   - one row per (commit, file): who, when, lines added/deleted, bug fix?
  * file features   - one row per file: commit count, churn, #developers, bug fixes, age...

Run from the project root:
    python -m pipeline.git_history https://github.com/psf/requests
    python -m pipeline.git_history path/to/local/repo --until 2024-01-01
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from git import GitCommandError, Repo

from pipeline.filters import is_source_file
from pipeline.errors import RepoNotFound  # noqa: F401  (re-exported)
from pipeline.paths import DATA_DIR

# ---------------------------------------------------------------------------
# Cloning
# ---------------------------------------------------------------------------

_GITHUB_URL = re.compile(r"github\.com[/:](?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$")


def clone_repo(source: str, dest_dir: str | Path = DATA_DIR / "repos") -> Path:
    """Return a local path to the repo. `source` is a GitHub URL or an existing local repo.

    URLs are cloned once into data/repos/<owner>__<repo> and fast-forwarded on later runs.
    A full clone is needed: history features use every commit.
    """
    local = Path(source)
    if local.exists():
        Repo(local)  # raises if it isn't a git repo
        return local

    m = _GITHUB_URL.search(source.strip())
    if not m:
        raise ValueError(f"Not a GitHub URL or local repo: {source}")
    target = Path(dest_dir) / f"{m['owner']}__{m['repo']}"
    if target.exists():
        try:
            repo = Repo(target)
            with repo.git.custom_environment(**_NO_PROMPT):
                repo.remotes.origin.pull(ff_only=True)
        except GitCommandError as e:  # offline / GitHub down: keep using the local copy
            logging.getLogger(__name__).warning("Could not update %s, using local copy: %s",
                                                target.name, str(e).strip().splitlines()[-1])
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            Repo.clone_from(f"https://github.com/{m['owner']}/{m['repo']}.git", target, env=_NO_PROMPT)
        except GitCommandError as e:
            shutil.rmtree(target, ignore_errors=True)  # don't leave a broken half-clone behind
            raise RepoNotFound(f"Could not clone {m['owner']}/{m['repo']}: the repository doesn't exist, "
                               f"is private, or GitHub is unreachable") from e
    return target


# Never wait for a username/password: a missing or private repo must fail at once instead
# of opening a login prompt (which would hang a background scan forever).
_NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never", "GIT_ASKPASS": "echo"}


# ---------------------------------------------------------------------------
# Bug-fix detection (keyword heuristic, as used in SZZ-style research)
# ---------------------------------------------------------------------------

_FIX_WORDS = re.compile(
    r"\b(fix(e[sd]|ing)?|bug(s|fix(es)?)?|hotfix(es)?|patch(ed)?|defect|fault|crash(es|ed)?"
    r"|regression|broken|incorrect|repair(ed)?)\b",
    re.IGNORECASE,
)
# Commits that say "fix" but aren't fixing code behaviour.
_NOT_FIX_WORDS = re.compile(
    r"\b(typos?|docs?|documentation|readme|whitespace|spelling|lint(ing)?|format(ting)?|changelog|pep ?8"
    r"|ci|build|mypy|flake8|black|isort|ruff|typing)\b",
    re.IGNORECASE,
)
# "Fixes #123" / "closes #45" anywhere in the message = closing a GitHub issue.
_CLOSES_ISSUE = re.compile(r"\b(fix(e[sd])?|close[sd]?|resolve[sd]?)\s+#\d+", re.IGNORECASE)


MAX_FIX_FILES = 10  # fix commits touching more source files than this are ignored as bug fixes


def is_bug_fix(message: str) -> bool:
    subject = message.strip().split("\n", 1)[0]
    if _NOT_FIX_WORDS.search(subject):
        return False
    return bool(_FIX_WORDS.search(subject) or _CLOSES_ISSUE.search(message))


def is_bot(name: str, email: str) -> bool:
    text = f"{name} {email}".lower()
    return "[bot]" in text or "dependabot" in text or "github-actions" in text


# ---------------------------------------------------------------------------
# Git log parsing
# ---------------------------------------------------------------------------

# Control characters can't appear in commit messages, so they make safe separators.
_REC, _FLD, _END = "\x1e", "\x1f", "\x1d"
# %at = Unix timestamp: always valid UTC, unlike ISO dates (real repos contain broken
# timezone offsets such as "+518:00"). %aN/%aE apply .mailmap to merge author aliases.
# %ai only for the author's timezone offset (local hour -> late-night commits), parsed tolerantly.
_FORMAT = f"{_REC}%H{_FLD}%at{_FLD}%ai{_FLD}%aN{_FLD}%aE{_FLD}%B{_END}"
_TZ = re.compile(r"([+-])(\d{2}):?(\d{2})$")


def _tz_offset_minutes(iso_date: str) -> int | None:
    """'2011-09-08 02:38:50 +0200' -> 120. Broken offsets (e.g. '+518:00') -> None."""
    m = _TZ.search(iso_date.strip())
    if not m:
        return None
    minutes = int(m[2]) * 60 + int(m[3])
    if minutes > 14 * 60 or int(m[3]) >= 60:
        return None
    return minutes if m[1] == "+" else -minutes


def extract_commits(
    repo_path: str | Path, extensions: tuple[str, ...] = (".py",), since: str | None = None
) -> pd.DataFrame:
    """Parse the history (merges skipped) into one row per (commit, file).

    Renames are followed: every row's `file_path` is the file's *latest* name, so a file
    moved from requests/x.py to src/requests/x.py keeps its whole history.

    `since` = a commit sha: only parse commits after it (incremental refresh, see
    pipeline/store.py). The renames found are returned in `df.attrs["renames"]` so older,
    cached rows can be renamed too.
    """
    repo = Repo(repo_path)
    rev_range = [f"{since}..HEAD"] if since else []
    raw: bytes = repo.git.log(
        "--no-merges", "-M", "--numstat", "-z", f"--format={_FORMAT}", *rev_range,
        stdout_as_string=False,
    )
    text = raw.decode("utf-8", errors="replace")  # old commits can contain broken encodings

    rows: list[dict] = []
    alias: dict[str, str] = {}  # old path -> latest path (log is newest-first)

    for record in text.split(_REC)[1:]:
        header, _, numstat = record.partition(_END)
        sha, timestamp, iso_date, name, email, message = header.split(_FLD, 5)
        message = message.strip()
        bot, fix = is_bot(name, email), is_bug_fix(message)
        commit_date = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        tz_offset = _tz_offset_minutes(iso_date)

        tokens = iter(numstat.split("\0"))
        for token in tokens:
            token = token.strip("\n")
            if not token:
                continue
            added, deleted, path = token.split("\t", 2)
            if path == "":  # rename: the old and new paths follow as separate tokens
                old, new = next(tokens), next(tokens)
                latest = alias.get(new, new)
                alias[old] = latest
                path_at_commit, change_type = new, "RENAME"
            else:
                latest = alias.get(path, path)
                path_at_commit, change_type = path, "MODIFY"

            if not is_source_file(latest, extensions):
                continue
            rows.append({
                "commit_sha": sha,
                "commit_date": commit_date,
                "tz_offset_min": tz_offset,
                "author": name,
                "author_email": email.lower(),
                "is_bot": bot,
                "file_path": latest,
                "path_at_commit": path_at_commit,
                "change_type": change_type,
                # "-" means binary file
                "lines_added": int(added) if added != "-" else 0,
                "lines_deleted": int(deleted) if deleted != "-" else 0,
                "is_bug_fix": fix,
                "commit_message": message,
            })

    df = finalize_commits(pd.DataFrame(rows))
    df.attrs["renames"] = alias
    return df


def finalize_commits(df: pd.DataFrame) -> pd.DataFrame:
    """Derived columns. Safe to run again on a combined (cached + new) table."""
    if df.empty:
        return df
    df = df.sort_values("commit_date", kind="stable").reset_index(drop=True)
    # A "fix" touching many files at once is a bulk change (CI repair, rename, reformat),
    # not a targeted bug fix - counting it would mark every touched file as buggy.
    df["files_in_commit"] = df.groupby("commit_sha")["file_path"].transform("size")
    fix_by_sha = df.drop_duplicates("commit_sha").set_index("commit_sha")["commit_message"].map(is_bug_fix)
    df["is_bug_fix"] = df["commit_sha"].map(fix_by_sha) & (df["files_in_commit"] <= MAX_FIX_FILES)
    # The oldest change to each file is the one that created it. Only plain MODIFY rows are
    # promoted, so a RENAME is never overwritten (matters when a new batch is finalized alone).
    first = ~df.duplicated("file_path", keep="first")
    df.loc[(df["change_type"] == "ADD") & ~first, "change_type"] = "MODIFY"
    df.loc[first & (df["change_type"] == "MODIFY"), "change_type"] = "ADD"
    return df


# ---------------------------------------------------------------------------
# Per-file features
# ---------------------------------------------------------------------------


def file_history_features(
    commits: pd.DataFrame, until: datetime | None = None, recent_days: int = 90
) -> pd.DataFrame:
    """Aggregate the commits table into one row per file, using only history *before* `until`.

    The cutoff matters for ML (A3): features must only use the past, never the future.
    """
    if commits.empty:
        return pd.DataFrame()
    until = until or (commits["commit_date"].max() + timedelta(seconds=1))
    if until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    df = commits[commits["commit_date"] < until].copy()
    if df.empty:
        return pd.DataFrame()

    df["churn"] = df["lines_added"] + df["lines_deleted"]
    df["is_recent"] = df["commit_date"] >= until - timedelta(days=recent_days)
    humans = df[~df["is_bot"]]

    g = df.groupby("file_path")
    out = pd.DataFrame({
        "commit_count": g["commit_sha"].nunique(),
        "lines_added": g["lines_added"].sum(),
        "lines_deleted": g["lines_deleted"].sum(),
        "churn": g["churn"].sum(),
        "bug_fix_count": df[df["is_bug_fix"]].groupby("file_path")["commit_sha"].nunique(),
        "num_developers": humans.groupby("file_path")["author_email"].nunique(),
        "first_commit": g["commit_date"].min(),
        "last_commit": g["commit_date"].max(),
        "recent_commit_count": df[df["is_recent"]].groupby("file_path")["commit_sha"].nunique(),
        "recent_churn": df[df["is_recent"]].groupby("file_path")["churn"].sum(),
    })
    # Ownership: share of commits by the file's main author. Low = nobody really owns it.
    per_author = humans.groupby(["file_path", "author_email"]).size()
    out["top_author_share"] = per_author.groupby("file_path").max() / humans.groupby("file_path").size()

    # Commit-message NLP signals (B1, ml/nlp.py), if present: share of the file's human
    # commits that sound frustrated / rushed / were late at night, etc.
    msg_cols = [c for c in df.columns if c.startswith("msg_")]
    if msg_cols:
        out = out.join(humans.groupby("file_path")[msg_cols].mean().round(3))

    count_cols = ["bug_fix_count", "num_developers", "recent_commit_count", "recent_churn"]
    out[count_cols] = out[count_cols].fillna(0).astype(int)
    out["top_author_share"] = out["top_author_share"].fillna(0).round(3)
    out["bug_fix_ratio"] = (out["bug_fix_count"] / out["commit_count"]).round(3)
    out["age_days"] = (until - out["first_commit"]).dt.days
    out["days_since_last_change"] = (until - out["last_commit"]).dt.days
    out["snapshot_date"] = until
    return out.sort_values("commit_count", ascending=False).reset_index()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Extract Git history features from a repo.")
    ap.add_argument("source", help="GitHub URL or local repo path")
    ap.add_argument("--out", default=str(DATA_DIR / "processed"), help="output folder")
    ap.add_argument("--until", help="only use history before this date (YYYY-MM-DD)")
    args = ap.parse_args()

    repo_path = clone_repo(args.source)
    name = repo_path.resolve().name
    commits = extract_commits(repo_path)
    until = datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc) if args.until else None
    features = file_history_features(commits, until=until)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    commits.to_csv(out / f"{name}_commits.csv", index=False)
    features.to_csv(out / f"{name}_file_history.csv", index=False)

    print(f"{name}: {commits['commit_sha'].nunique()} commits touching {len(features)} files "
          f"({int(commits.drop_duplicates('commit_sha')['is_bug_fix'].sum())} bug-fix commits)")
    print(f"Saved to {out}/{name}_commits.csv and {name}_file_history.csv")


if __name__ == "__main__":
    main()
