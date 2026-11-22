"""A1 - Git history extraction."""

from datetime import datetime, timezone

import pytest

from pipeline.filters import is_vendored
from pipeline.git_history import (_tz_offset_minutes, extract_commits, file_history_features,
                                  is_bot, is_bug_fix)


@pytest.mark.parametrize("message,expected", [
    ("Fix crash when url is None", True),
    ("Add retries. Fixes #42", True),
    ("fixed this stupid bug again", True),
    ("Fix typo in docs", False),
    ("Fix CI and build failures (#7190)", False),
    ("Fix mypy errors", False),
    ("Update README", False),
    ("Add support for proxies", False),
])
def test_bug_fix_detection(message, expected):
    assert is_bug_fix(message) is expected


def test_timezone_parsing_tolerates_broken_offsets():
    assert _tz_offset_minutes("2011-09-08 02:38:50 +0200") == 120
    assert _tz_offset_minutes("2020-01-01 10:00:00 -0530") == -330
    assert _tz_offset_minutes("2011-09-08 02:38:50 +51800") is None  # real-world garbage


def test_bot_and_vendor_filters():
    assert is_bot("dependabot[bot]", "x@users.noreply.github.com")
    assert not is_bot("Alice", "alice@example.com")
    assert is_vendored("requests/packages/urllib3/poolmanager.py")
    assert is_vendored("src/vendor/lib.py")
    assert not is_vendored("packages/core/app.py")  # top-level monorepo folder is fine


def test_extract_commits(repo):
    c = extract_commits(repo["path"])
    assert c["commit_sha"].nunique() == 60
    assert set(c["file_path"]) >= {"pkg/core.py", "pkg/utils.py", "pkg/new_name.py"}
    assert c["commit_date"].is_monotonic_increasing
    # "Fix crash in core parser" every 5th commit, touching few files -> bug fix
    fixes = c.drop_duplicates("commit_sha")
    assert fixes["is_bug_fix"].sum() == 12
    assert not fixes[fixes["commit_message"].str.startswith("Fix typo")]["is_bug_fix"].any()


def test_rename_keeps_history(repo):
    c = extract_commits(repo["path"])
    renamed = c[c["file_path"] == "pkg/new_name.py"]
    assert "pkg/old_name.py" in set(renamed["path_at_commit"])  # history from before the rename
    assert "pkg/old_name.py" not in set(c["file_path"])  # no leftover under the old name
    assert (renamed["change_type"] == "RENAME").sum() == 1


def test_file_features_respect_cutoff(repo):
    c = extract_commits(repo["path"])
    cutoff = datetime(2023, 1, 1, tzinfo=timezone.utc)
    f = file_history_features(c, until=cutoff).set_index("file_path")
    core = c[(c["file_path"] == "pkg/core.py") & (c["commit_date"] < cutoff)]
    assert f.loc["pkg/core.py", "commit_count"] == core["commit_sha"].nunique()
    assert f.loc["pkg/core.py", "num_developers"] == 3
    assert (f["last_commit"] < cutoff).all()  # nothing from the future
