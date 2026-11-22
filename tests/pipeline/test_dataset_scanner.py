"""A3/A4 - Leak-free dataset, incremental cache, scanner."""

import pandas as pd
from git import Repo

from pipeline.dataset import LABEL_COLS, META_COLS, build_dataset
from pipeline.git_history import extract_commits
from pipeline.scanner import changed_source_files, scan_repository
from pipeline.store import load_commits


def test_dataset_has_no_future_information(repo):
    df = build_dataset(str(repo["path"]), interval_months=6, horizon_months=6)
    assert not df.empty and df["snapshot_date"].nunique() >= 2
    commits = extract_commits(repo["path"])
    for _, row in df.sample(min(10, len(df)), random_state=0).iterrows():
        t, end = row["snapshot_date"], row["snapshot_date"] + pd.DateOffset(months=6)
        mine = commits[commits["file_path"] == row["file_path"]]
        # features only count commits BEFORE the snapshot...
        assert row["commit_count"] == mine[mine["commit_date"] < t]["commit_sha"].nunique()
        # ...labels only count bug fixes in the 6 months AFTER it
        fixes = mine[(mine["commit_date"] >= t) & (mine["commit_date"] < end) & mine["is_bug_fix"]]
        assert row["future_bug_fixes"] == fixes["commit_sha"].nunique()
    assert not df["is_test_file"].any()  # tests excluded by default


def test_incremental_cache_equals_full_parse(repo, tmp_path):
    clone = tmp_path / "clone"
    Repo.clone_from(str(repo["path"]), clone)
    r = Repo(clone)
    r.git.reset("--hard", "HEAD~35")  # cache an older state (before the rename at commit 30)
    load_commits(clone, cache_dir=tmp_path / "cache")
    r.git.reset("--hard", "origin/main")
    incremental = load_commits(clone, cache_dir=tmp_path / "cache")
    full = extract_commits(clone)
    cols = list(full.columns)
    key = ["commit_sha", "path_at_commit", "file_path"]
    a = incremental[cols].sort_values(key).reset_index(drop=True)
    b = full[cols].sort_values(key).reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_scanner_features_match_training_columns(repo):
    result = scan_repository(str(repo["path"]), history_points=2)
    train = build_dataset(str(repo["path"]))
    feats = [c for c in train.columns if c not in META_COLS + LABEL_COLS]
    assert set(feats) <= set(result.features.columns)
    assert len(result.history) == 2 and result.history[0].date < result.history[1].date
    assert len(result.commits) > 0 and "msg_frustrated" in result.commits.columns


def test_changed_files_of_a_pull_request(repo):
    changed = changed_source_files(repo["path"], repo["base_sha"], repo["head_sha"])
    assert sorted(changed) == ["pkg/core.py", "pkg/feature.py"]
