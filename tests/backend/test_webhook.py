"""Backend: GitHub webhook security, events, PR review + comment (fake GitHub API)."""

import hashlib
import hmac
import json
import uuid

import httpx
import pytest

from app.config import settings
from app.db.session import SessionLocal
from app.models import Scan, ScanStatus
from app.services.github_app import GitHubClient, set_client, verify_signature

SECRET = "test-webhook-secret"


def send(client, event, payload, secret=SECRET, delivery=None, raw: bytes | None = None):
    body = raw if raw is not None else json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.post("/api/github/webhook", content=body, headers={
        "X-GitHub-Event": event, "X-Hub-Signature-256": sig,
        "X-GitHub-Delivery": delivery or str(uuid.uuid4()), "Content-Type": "application/json"})


def test_signature_helper():
    body = b'{"a": 1}'
    good = "sha256=" + hmac.new(b"s", body, hashlib.sha256).hexdigest()
    assert verify_signature(body, good, "s")
    assert not verify_signature(body, good, "other")
    assert not verify_signature(body + b" ", good, "s")  # tampered body
    assert not verify_signature(body, None, "s") and not verify_signature(body, good, "")


def test_webhook_security(client, monkeypatch):
    assert send(client, "ping", {}, secret="attacker").status_code == 401
    assert client.post("/api/github/webhook", content=b"{}", headers={"X-GitHub-Event": "ping"}).status_code == 401
    assert send(client, "ping", {}, raw=b"not json").status_code == 400
    d = str(uuid.uuid4())
    assert send(client, "ping", {}, delivery=d).json() == {"status": "pong"}
    assert send(client, "ping", {}, delivery=d).json() == {"status": "duplicate"}
    monkeypatch.setattr(settings, "github_webhook_secret", "")
    assert send(client, "ping", {}).status_code == 503  # fail closed without a secret


def test_oversized_payload_rejected(client):
    huge = b"{" + b" " * (26 * 1024 * 1024) + b"}"
    assert send(client, "ping", {}, raw=huge).status_code == 413


@pytest.fixture
def fake_github(monkeypatch, offline_github):
    """GitHub API replaced by a fake; PR fetch served by the synthetic repo's feature branch."""
    import pipeline.scanner as scanner

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        assert request.headers["authorization"] == "Bearer test-pat"
        assert "<!-- code-risk-predictor -->" in json.loads(request.content)["body"]
        if request.method == "POST":
            return httpx.Response(201, json={"id": 777})
        return httpx.Response(200, json={"id": 777})

    monkeypatch.setattr(settings, "github_token", "test-pat")
    monkeypatch.setattr(scanner, "fetch_pull_request",
                        lambda source, number: (offline_github["path"], offline_github["head_sha"]))
    set_client(GitHubClient(transport=httpx.MockTransport(handler)))
    yield calls
    set_client(None)


def test_pull_request_review_posts_then_updates_comment(client, auth, fake_github, repo):
    rid = client.post("/api/repositories", json={"url": "https://github.com/acme/widgets"}, headers=auth).json()["id"]
    pr = {"action": "opened", "installation": {"id": 5}, "repository": {"full_name": "ACME/widgets"},
          "pull_request": {"number": 12, "head": {"sha": repo["head_sha"]}, "base": {"sha": repo["base_sha"]}}}
    r = send(client, "pull_request", pr)
    assert r.json()["status"] == "queued"
    scan = client.get(f"/api/scans/{r.json()['scan_id']}", headers=auth).json()
    assert scan["status"] == "completed" and scan["error_message"] is None, scan["error_message"]
    assert fake_github == [("POST", "/repos/acme/widgets/issues/12/comments")]
    report = scan["report_markdown"]
    assert "pkg/core.py" in report and "pkg/feature.py" in report and "new file" in report
    assert "▲" in report  # the PR made core.py more complex -> riskier than on main
    assert send(client, "pull_request", pr).json()["status"] == "duplicate"

    # a later run for the same PR updates the same comment instead of adding a new one
    with SessionLocal() as db:  # pretend the first run failed so the same commit is reviewed again
        db.get(Scan, r.json()["scan_id"]).status = ScanStatus.failed
        db.commit()
    fake_github.clear()
    assert send(client, "pull_request", {**pr, "action": "synchronize"}).json()["status"] == "queued"
    assert fake_github == [("PATCH", "/repos/acme/widgets/issues/comments/777")]

    # PR reviews stay out of the repo's main-branch views
    assert client.get(f"/api/repositories/{rid}", headers=auth).json()["latest_scan"] is None
    assert client.get(f"/api/repositories/{rid}/trends", headers=auth).json() == []


def test_other_events(client, auth, offline_github):
    client.post("/api/repositories", json={"url": "https://github.com/acme/widgets"}, headers=auth)
    pr = {"action": "closed", "repository": {"full_name": "acme/widgets"}, "pull_request": {"number": 1}}
    assert send(client, "pull_request", pr).json()["status"] == "ignored"
    unknown = {"action": "opened", "repository": {"full_name": "someone/else"}, "pull_request": {}}
    assert "not registered" in send(client, "pull_request", unknown).json()["reason"]
    repo_info = {"full_name": "acme/widgets", "default_branch": "main"}
    assert send(client, "push", {"ref": "refs/heads/feature", "repository": repo_info}).json()["status"] == "ignored"
    pushed = send(client, "push", {"ref": "refs/heads/main", "repository": repo_info}).json()
    assert pushed["status"] == "queued" and len(pushed["scan_ids"]) == 1
    inst = send(client, "installation_repositories", {"action": "added", "installation": {"id": 99},
                                                       "repositories_added": [{"full_name": "Acme/Widgets"}]})
    assert inst.json() == {"status": "ok"}
    assert send(client, "issues", {}).json()["status"] == "ignored"
