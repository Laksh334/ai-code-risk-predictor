"""Backend: real scan job (pipeline + model) on the synthetic repo, failures, dashboard data."""

from app.db.session import SessionLocal
from app.models import Scan, ScanStatus
from app.services.analysis import fail_interrupted_scans
from pipeline.git_history import RepoNotFound


def _repo(client, auth):
    return client.post("/api/repositories", json={"url": "https://github.com/acme/widgets"}, headers=auth).json()["id"]


def test_scan_runs_pipeline_and_model(client, auth, offline_github):
    rid = _repo(client, auth)
    s = client.post(f"/api/repositories/{rid}/scans", headers=auth)
    assert s.status_code == 202 and s.json()["status"] == "pending"  # answers before the work
    detail = client.get(f"/api/scans/{s.json()['id']}", headers=auth).json()  # background task has run
    assert detail["status"] == "completed", detail["error_message"]
    assert detail["total_files"] >= 4 and detail["model_version"].startswith("logistic")
    assert sum(detail["risk_counts"].values()) == detail["total_files"]
    card = client.get("/api/repositories", headers=auth).json()[0]  # dashboard card summary
    assert card["report_scan_id"] == detail["id"] and card["risk_counts"] == detail["risk_counts"]

    files = client.get(f"/api/scans/{detail['id']}/files", headers=auth).json()["items"]
    assert [f["priority_rank"] for f in files] == sorted(f["priority_rank"] for f in files)
    top = files[0]
    assert top["file_path"] == "pkg/core.py"  # the module that grew most complex
    assert top["factors"] and top["explanation"] and top["recommendation"] and top["metrics"]
    one = client.get(f"/api/scans/{detail['id']}/files/{top['id']}", headers=auth).json()
    assert one["file_path"] == "pkg/core.py"

    # first scan back-fills history: HISTORY_POINTS=3 in the test env -> 4 trend points
    assert len(client.get(f"/api/repositories/{rid}/trends", headers=auth).json()) == 4
    forecast = client.get(f"/api/repositories/{rid}/debt-forecast", headers=auth).json()
    assert len(forecast["history"]) == 4 and len(forecast["projection"]) == 3
    hist = client.get(f"/api/repositories/{rid}/file-history", params={"path": "pkg/core.py"}, headers=auth).json()
    assert len(hist["risk_over_time"]) == 4 and hist["recent_commits"]
    assert client.get(f"/api/repositories/{rid}/scans", headers=auth).json()["total"] == 1  # history hidden here

    # a second scan doesn't back-fill again
    client.post(f"/api/repositories/{rid}/scans", headers=auth)
    assert len(client.get(f"/api/repositories/{rid}/trends", headers=auth).json()) == 5


def test_file_filters_and_sorting(client, auth, offline_github):
    rid = _repo(client, auth)
    sid = client.post(f"/api/repositories/{rid}/scans", headers=auth).json()["id"]
    q = client.get(f"/api/scans/{sid}/files", params={"q": "core"}, headers=auth).json()
    assert [f["file_path"] for f in q["items"]] == ["pkg/core.py"]
    by_loc = client.get(f"/api/scans/{sid}/files", params={"sort": "loc"}, headers=auth).json()["items"]
    assert [f["loc"] for f in by_loc] == sorted((f["loc"] for f in by_loc), reverse=True)
    assert client.get(f"/api/scans/{sid}/files", params={"sort": "hack"}, headers=auth).status_code == 422
    page = client.get(f"/api/scans/{sid}/files", params={"limit": 2, "offset": 1}, headers=auth).json()
    assert len(page["items"]) == 2 and page["total"] >= 4


def test_failed_scan_reports_reason(client, auth, monkeypatch):
    import pipeline.scanner as scanner

    def missing(*a, **k):
        raise RepoNotFound("Could not clone acme/widgets: the repository doesn't exist")

    monkeypatch.setattr(scanner, "clone_repo", missing)
    rid = _repo(client, auth)
    sid = client.post(f"/api/repositories/{rid}/scans", headers=auth).json()["id"]
    d = client.get(f"/api/scans/{sid}", headers=auth).json()
    assert d["status"] == "failed" and "doesn't exist" in d["error_message"]
    # a failed scan doesn't block the next one
    assert client.post(f"/api/repositories/{rid}/scans", headers=auth).status_code == 202


def test_repo_without_python_files_explains_why(client, auth, monkeypatch, tmp_path):
    """A TypeScript-only repo (like a React app) can't be scored: say so instead of crashing."""
    import subprocess

    import pipeline.scanner as scanner

    repo = tmp_path / "react-app"
    (repo / "src").mkdir(parents=True)
    for i in range(3):
        (repo / "src" / f"Page{i}.tsx").write_text(f"export const Page{i} = () => <div>{i}</div>;\n")
    (repo / "src" / "api.ts").write_text("export const get = (u: string) => fetch(u);\n")
    (repo / "package.json").write_text("{}\n")
    for cmd in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git", *cmd], cwd=repo, check=True, capture_output=True)
    monkeypatch.setattr(scanner, "clone_repo", lambda source, *a, **k: repo)

    rid = _repo(client, auth)
    sid = client.post(f"/api/repositories/{rid}/scans", headers=auth).json()["id"]
    d = client.get(f"/api/scans/{sid}", headers=auth).json()
    assert d["status"] == "failed"
    assert d["error_message"].startswith("No Python source files found")  # plain sentence, no error type
    assert ".tsx (3)" in d["error_message"] and ".ts (1)" in d["error_message"]
    assert "ValueError" not in d["error_message"]


def test_only_one_scan_at_a_time_and_restart_recovery(client, auth):
    rid = _repo(client, auth)
    with SessionLocal() as db:
        db.add(Scan(repository_id=rid, status=ScanStatus.running))
        db.commit()
    assert client.post(f"/api/repositories/{rid}/scans", headers=auth).status_code == 409
    fail_interrupted_scans()  # what happens at server start-up
    with SessionLocal() as db:
        s = db.query(Scan).one()
        assert s.status == ScanStatus.failed and "restart" in s.error_message


def test_debt_forecast_without_scans_is_404(client, auth):
    rid = _repo(client, auth)
    assert client.get(f"/api/repositories/{rid}/debt-forecast", headers=auth).status_code == 404
