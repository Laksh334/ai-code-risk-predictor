"""Shared test setup. Everything runs offline and in a throwaway folder:

* RISK_DATA_DIR -> temp folder (clones, caches never touch the real data/)
* RISK_USE_HF=0 -> no 330 MB emotion model needed
* DATABASE_URL  -> temp SQLite file, tables recreated for every backend test
* a small synthetic git repository with dated commits, bug fixes, a rename and a PR branch
  stands in for GitHub
"""

import os
import shutil
import stat
import subprocess
import tempfile
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TMP = Path(tempfile.mkdtemp(prefix="riskpred-tests-"))
os.environ.update({
    "RISK_DATA_DIR": str(TMP / "data"),
    "RISK_USE_HF": "0",
    "RISK_MODEL_PATH": str(ROOT / "data" / "models" / "production.joblib"),
    "DATABASE_URL": f"sqlite:///{(TMP / 'test.db').as_posix()}",
    "SECRET_KEY": "test-secret-key-" + "x" * 32,
    "GITHUB_WEBHOOK_SECRET": "test-webhook-secret",
    "HISTORY_POINTS": "3",
})


def _force_remove(func, path, _exc):
    """git marks its object files read-only; on Windows they must be made writable to delete."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def pytest_sessionfinish(session, exitstatus):
    """Delete the temp folder. On Windows a folder can't be removed while a process uses it:
    GitPython keeps helper `git cat-file` processes alive per Repo object (closed when the object
    is garbage-collected) and SQLAlchemy keeps the SQLite file open."""
    import gc

    from app.db.session import engine

    engine.dispose()
    for _ in range(10):
        gc.collect()  # Repo.__del__ ends its git helper processes
        try:
            shutil.rmtree(TMP, onexc=_force_remove)
            return
        except OSError:
            time.sleep(0.5)
    shutil.rmtree(TMP, ignore_errors=True)  # never fail the test run over cleanup


# ---------------------------------------------------------------------------
# Synthetic repository
# ---------------------------------------------------------------------------

AUTHORS = [("Alice", "alice@example.com"), ("Bob", "bob@example.com"), ("Carol", "carol@example.com")]


def _git(repo: Path, *args: str, date: str | None = None, author=AUTHORS[0]) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": author[0], "GIT_AUTHOR_EMAIL": author[1],
           "GIT_COMMITTER_NAME": author[0], "GIT_COMMITTER_EMAIL": author[1]}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    out = subprocess.run(["git", *args], cwd=repo, env=env, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def _core(n: int) -> str:
    """A module that gets more complex with every version."""
    branches = "\n".join(
        f"    if x == {i}:\n        for j in range({i}):\n            if j % 2:\n                total += j\n"
        for i in range(n))
    return f"def parse(x):\n    total = 0\n{branches}    return total\n\n\ndef helper(a, b):\n    return a + b\n"


def build_repo(path: Path) -> dict:
    """60 commits over ~2 years (2022-2023). Returns facts the tests check against."""
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    (path / "pkg").mkdir()
    (path / "tests").mkdir()
    (path / "pkg" / "__init__.py").write_text("from .core import parse\n")
    (path / "pkg" / "utils.py").write_text("from .core import helper\n\ndef add(a, b):\n    return helper(a, b)\n")
    (path / "pkg" / "old_name.py").write_text("VALUE = 1\n")
    (path / "tests" / "test_core.py").write_text("from pkg.core import parse\n\ndef test():\n    assert parse(0) == 0\n")
    messages = ["Add feature {i}", "Fix crash in core parser", "WIP", "Fix typo in docs", "Refactor utils"]
    for i in range(60):
        day = 1 + (i * 12) % 28
        month = 1 + (i * 12 // 28) % 12
        year = 2022 + (i * 12) // 336
        hour = 23 if i % 7 == 0 else 14  # some late-night commits
        date = f"{year}-{month:02d}-{day:02d}T{hour}:00:00+0200"
        (path / "pkg" / "core.py").write_text(_core(1 + i // 4) + f"\n# revision {i}\n")  # always a change
        if i % 3 == 0:
            (path / "pkg" / "utils.py").write_text(
                (path / "pkg" / "utils.py").read_text() + f"\n\ndef f{i}(v):\n    return v * {i}\n")
        if i == 30:  # a rename half-way through
            _git(path, "mv", "pkg/old_name.py", "pkg/new_name.py")
        if i > 30 and i % 5 == 0:
            (path / "pkg" / "new_name.py").write_text(f"VALUE = {i}\n")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "-m", messages[i % len(messages)].format(i=i), date=date,
             author=AUTHORS[i % 3])
    base = _git(path, "rev-parse", "HEAD")
    # A pull-request branch: makes core.py more complex and adds a new module.
    _git(path, "checkout", "-q", "-b", "feature")
    (path / "pkg" / "core.py").write_text(_core(40))
    (path / "pkg" / "feature.py").write_text("def new_feature(x):\n    if x:\n        return 1\n    return 0\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "Add new feature", date="2024-06-01T10:00:00+0200")
    head = _git(path, "rev-parse", "HEAD")
    _git(path, "checkout", "-q", "main")
    return {"path": path, "base_sha": base, "head_sha": head}


@pytest.fixture(scope="session")
def repo() -> dict:
    return build_repo(TMP / "repos" / "acme__widgets")


@pytest.fixture
def offline_github(monkeypatch, repo):
    """Make every "clone https://github.com/..." use the synthetic repo instead."""
    import pipeline.scanner as scanner

    monkeypatch.setattr(scanner, "clone_repo", lambda source, *a, **k: repo["path"])
    return repo


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import app.models  # noqa: F401
    from app.db.session import Base, engine
    from app.main import app
    from app.services.rate_limit import login_limiter

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_limiter.reset()
    with TestClient(app) as c:
        yield c


def make_user(client, email: str = "user@example.com", password: str = "testpass123") -> dict:
    client.post("/api/auth/register", json={"email": email, "password": password})
    token = client.post("/api/auth/login", data={"username": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth(client) -> dict:
    return make_user(client)
