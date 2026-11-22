"""A3 - Build the ML training dataset with time-based snapshots.

For each snapshot date T (e.g. every 6 months):
  features = Git history BEFORE T (A1)  +  static metrics of the code AS IT WAS at T (A2)
  label    = what happened to the file in the NEXT `horizon` months (T .. T+horizon):
               future_bug_fixes  - number of bug-fix commits    -> label_bug_prone (>= 1)
               future_churn      - lines changed (maintenance cost)

Features only ever look at the past and labels only at the future, so the model learns to
*predict* risk - exactly how it will be used on a live repo. Snapshots whose future window
runs past the last commit are dropped (their labels would be incomplete).

    python -m pipeline.dataset data/repos/psf__requests
    python -m pipeline.dataset https://github.com/psf/requests https://github.com/pallets/flask --interval 3
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from pipeline.git_history import clone_repo, file_history_features
from ml.nlp import add_message_features
from pipeline.store import cached_static_analysis, load_commits
from pipeline.paths import DATA_DIR

# Columns that are NOT model inputs. Everything else numeric is a feature.
META_COLS = ["repo", "file_path", "path_at_snapshot", "snapshot_date", "horizon_months", "parse_ok"]
LABEL_COLS = ["future_bug_fixes", "future_commits", "future_churn", "label_bug_prone"]

HISTORY_COLS = [
    "commit_count", "lines_added", "lines_deleted", "churn", "bug_fix_count", "num_developers",
    "recent_commit_count", "recent_churn", "top_author_share", "bug_fix_ratio",
    "age_days", "days_since_last_change",
]


def snapshot_dates(
    commits: pd.DataFrame, interval_months: int, horizon_months: int, warmup_months: int = 12
) -> list[pd.Timestamp]:
    """Every `interval` months, starting after `warmup` months of history (so features mean
    something) and ending early enough that the full label window is observed."""
    first, last = commits["commit_date"].min(), commits["commit_date"].max()
    start = (first + pd.DateOffset(months=warmup_months)).normalize().replace(day=1)
    end = last - pd.DateOffset(months=horizon_months)
    return list(pd.date_range(start, end, freq=pd.DateOffset(months=interval_months)))


def _paths_at(commits: pd.DataFrame, when: pd.Timestamp) -> dict[str, str]:
    """Map 'path as it was at `when`' -> the file's canonical (latest) name used by A1.
    Needed because A2 sees e.g. requests/models.py in 2013, A1 calls it src/requests/models.py."""
    past = commits[commits["commit_date"] < when]
    latest = past.drop_duplicates("path_at_commit", keep="last")
    return dict(zip(latest["path_at_commit"], latest["file_path"]))


def future_labels(commits: pd.DataFrame, start: pd.Timestamp, horizon_months: int) -> pd.DataFrame:
    end = start + pd.DateOffset(months=horizon_months)
    win = commits[(commits["commit_date"] >= start) & (commits["commit_date"] < end)]
    win = win.assign(churn=win["lines_added"] + win["lines_deleted"])
    g = win.groupby("file_path")
    return pd.DataFrame({
        "future_bug_fixes": win[win["is_bug_fix"]].groupby("file_path")["commit_sha"].nunique(),
        "future_commits": g["commit_sha"].nunique(),
        "future_churn": g["churn"].sum(),
    })


def snapshot_features(
    repo_path: Path, commits: pd.DataFrame, when: pd.Timestamp, rev: str | None = None
) -> pd.DataFrame:
    """Features of every file at time `when`: static metrics of the code at `rev` (default:
    last commit before `when`) + Git history before `when`.
    Used for training snapshots (A3) AND live scans (A4), so both get identical columns."""
    static = cached_static_analysis(repo_path, rev or when.strftime("%Y-%m-%d"))
    if static.empty:
        return static
    static = static.rename(columns={"file_path": "path_at_snapshot"})
    alias = _paths_at(commits, when)
    static["file_path"] = static["path_at_snapshot"].map(lambda p: alias.get(p, p))

    history = file_history_features(commits, until=when.to_pydatetime()).drop(columns="snapshot_date")
    df = static.merge(history, on="file_path", how="left")
    # A file with no matching commits before T (e.g. it only arrived via a merge) has zero history.
    df[HISTORY_COLS] = df[HISTORY_COLS].fillna(0)
    df["snapshot_date"] = when
    return df


def build_snapshot(
    repo_path: Path, commits: pd.DataFrame, when: pd.Timestamp, horizon_months: int
) -> pd.DataFrame:
    df = snapshot_features(repo_path, commits, when)
    if df.empty:
        return df
    labels = future_labels(commits, when, horizon_months)
    df = df.merge(labels, left_on="file_path", right_index=True, how="left")
    label_cols = ["future_bug_fixes", "future_commits", "future_churn"]
    df[label_cols] = df[label_cols].fillna(0).astype(int)
    df["label_bug_prone"] = (df["future_bug_fixes"] > 0).astype(int)
    df["horizon_months"] = horizon_months
    return df


def build_dataset(
    source: str,
    interval_months: int = 6,
    horizon_months: int = 6,
    include_tests: bool = False,
) -> pd.DataFrame:
    repo_path = clone_repo(source)
    commits = add_message_features(load_commits(repo_path))  # cached (A4) + NLP signals (B1)
    if commits.empty:
        return pd.DataFrame()

    parts = []
    for when in snapshot_dates(commits, interval_months, horizon_months):
        snap = build_snapshot(repo_path, commits, when, horizon_months)
        if not snap.empty:
            parts.append(snap)
    if not parts:
        return pd.DataFrame()

    df = pd.concat(parts, ignore_index=True)
    if not include_tests:
        # The product scores source modules; test files change *because of* fixes elsewhere.
        df = df[~df["is_test_file"]]
    df.insert(0, "repo", repo_path.resolve().name)
    drop = ["first_commit", "last_commit", "commit_sha"]
    return df.drop(columns=[c for c in drop if c in df.columns]).reset_index(drop=True)


def summarize(df: pd.DataFrame) -> pd.DataFrame:
    """Per snapshot: files, positives and positive rate - spot class imbalance early."""
    return (
        df.groupby(["repo", df["snapshot_date"].dt.date])
        .agg(files=("file_path", "size"), bug_prone=("label_bug_prone", "sum"))
        .assign(rate=lambda s: (s["bug_prone"] / s["files"]).round(2))
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Build the time-based ML dataset from one or more repos.")
    ap.add_argument("sources", nargs="+", help="GitHub URLs or local repo paths")
    ap.add_argument("--interval", type=int, default=6, help="months between snapshots")
    ap.add_argument("--horizon", type=int, default=6, help="months to look ahead for labels")
    ap.add_argument("--include-tests", action="store_true")
    ap.add_argument("--out", default=str(DATA_DIR / "processed" / "dataset.csv"))
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    frames = [build_dataset(s, args.interval, args.horizon, args.include_tests) for s in args.sources]
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)

    pd.set_option("display.width", 200)
    print(summarize(df).to_string())
    secs = (datetime.now(timezone.utc) - started).total_seconds()
    print(f"\n{len(df)} rows, {df['snapshot_date'].nunique()} snapshots, "
          f"{df['label_bug_prone'].mean():.1%} bug-prone, {df.shape[1]} columns "
          f"-> {out} ({secs:.0f}s)")


if __name__ == "__main__":
    main()
