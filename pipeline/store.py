"""A4 - Commit cache with incremental refresh.

Parsing a big repo's full history every time is slow, so the commits table is cached in
data/cache/. On the next run only commits newer than the cached HEAD are parsed and
appended. If history was rewritten (force-push), the cache is rebuilt from scratch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
from git import Repo

from pipeline.filters import is_source_file
from pipeline.git_history import extract_commits, finalize_commits
from pipeline.paths import DATA_DIR

log = logging.getLogger(__name__)
DEFAULT_CACHE = DATA_DIR / "cache"
# Bump whenever the commits table gets new/changed columns: old caches are then rebuilt.
CACHE_VERSION = 2


def cached_static_analysis(
    repo_path: str | Path, rev: str, cache_dir: str | Path = DEFAULT_CACHE
) -> pd.DataFrame:
    """Static metrics at `rev`, cached by commit sha. Code at a past commit never changes,
    so every refresh only analyses snapshots it hasn't seen before."""
    from pipeline.static_analysis import analyze_repository, resolve_rev

    sha = resolve_rev(Repo(repo_path), rev)
    target = Path(cache_dir) / "static" / f"{Path(repo_path).resolve().name}_{sha}.pkl"
    if target.exists():
        return pd.read_pickle(target)
    df = analyze_repository(repo_path, rev=sha)
    target.parent.mkdir(parents=True, exist_ok=True)
    df.to_pickle(target)
    return df


def _apply_renames(paths: pd.Series, renames: dict[str, str]) -> pd.Series:
    return paths.map(lambda p: renames.get(p, p))


def load_commits(repo_path: str | Path, cache_dir: str | Path = DEFAULT_CACHE) -> pd.DataFrame:
    """The repo's commits table, updated to its current HEAD, using the cache when possible."""
    repo_path = Path(repo_path)
    repo = Repo(repo_path)
    head = repo.head.commit.hexsha

    cache_dir = Path(cache_dir)
    name = repo_path.resolve().name
    data_file, meta_file = cache_dir / f"{name}_commits.pkl", cache_dir / f"{name}_commits.json"

    cached, last = None, None
    if data_file.exists() and meta_file.exists():
        meta = json.loads(meta_file.read_text())
        if meta.get("version") == CACHE_VERSION:
            cached, last = pd.read_pickle(data_file), meta["head"]
        else:
            log.info("%s: cache format changed, rebuilding", name)

    if cached is not None and last == head:
        log.info("%s: cache up to date (%s)", name, head[:10])
        return cached

    try:
        incremental = cached is not None and repo.is_ancestor(last, head)
    except Exception:  # cached sha no longer exists in the repo
        incremental = False

    if incremental:
        new = extract_commits(repo_path, since=last)
        renames = new.attrs.get("renames", {})
        old = cached.copy()
        # A rename in the new commits changes the latest name of files already in the cache.
        old["file_path"] = _apply_renames(old["file_path"], renames)
        combined = pd.concat([old, new], ignore_index=True)
        combined = combined[combined["file_path"].map(is_source_file)]
        df = finalize_commits(combined)
        log.info("%s: +%d new commits (incremental)", name, new["commit_sha"].nunique() if len(new) else 0)
    else:
        df = extract_commits(repo_path)
        log.info("%s: full history parsed (%d commits)", name, df["commit_sha"].nunique() if len(df) else 0)

    df.attrs = {}
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_pickle(data_file)
    meta_file.write_text(json.dumps({"head": head, "version": CACHE_VERSION}))
    return df
