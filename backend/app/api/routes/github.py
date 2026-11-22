"""C2 - GitHub App webhook receiver.

GitHub POSTs every event here. Events handled:
  ping                                  -> sanity check when the App is set up
  installation / installation_repositories -> remember which installation covers which repo
  pull_request (opened, synchronize, reopened, ready_for_review)
                                        -> queue a PR review; the result is commented on the PR
  push to the default branch            -> queue a normal scan, keeping the dashboard fresh

Security: requests without a valid HMAC signature are rejected, and with no secret configured
every request is refused (fail closed). GitHub expects an answer within 10 s, so the real work
always runs as a background task.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from sqlalchemy import func, select

from app.api.deps import DbSession
from app.config import settings
from app.models import Repository, Scan, ScanStatus, ScanTrigger
from app.services.analysis import run_scan
from app.services.github_app import verify_signature
from app.services.pr_review import run_pr_scan

router = APIRouter(prefix="/github", tags=["github"])
log = logging.getLogger(__name__)

PR_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
MAX_BODY_BYTES = 25 * 1024 * 1024  # GitHub caps webhook payloads at 25 MB
_seen_deliveries: OrderedDict[str, None] = OrderedDict()  # GitHub may redeliver the same event


def _already_seen(delivery_id: str | None) -> bool:
    if not delivery_id:
        return False
    if delivery_id in _seen_deliveries:
        return True
    _seen_deliveries[delivery_id] = None
    if len(_seen_deliveries) > 1000:
        _seen_deliveries.popitem(last=False)
    return False


def _repos_named(db, full_name: str) -> list[Repository]:
    return list(db.scalars(
        select(Repository).where(func.lower(Repository.full_name) == full_name.lower()).order_by(Repository.id)
    ))


def _active_scan(db, repo_id: int) -> int | None:
    return db.scalar(select(Scan.id).where(
        Scan.repository_id == repo_id, Scan.status.in_([ScanStatus.pending, ScanStatus.running]),
        Scan.trigger != ScanTrigger.pull_request))


@router.post("/webhook", status_code=status.HTTP_202_ACCEPTED)
async def webhook(
    request: Request,
    background: BackgroundTasks,
    db: DbSession,
    x_github_event: str = Header(...),
    x_hub_signature_256: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
) -> dict:
    if not settings.github_webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Webhook secret not configured")
    if int(request.headers.get("content-length") or 0) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Payload too large")
    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")
    if _already_seen(x_github_delivery):
        return {"status": "duplicate"}
    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Body is not valid JSON") from None

    if x_github_event == "ping":
        return {"status": "pong"}

    if x_github_event in ("installation", "installation_repositories"):
        inst_id = payload["installation"]["id"]
        removed = payload.get("action") == "deleted"
        added = payload.get("repositories", []) + payload.get("repositories_added", [])
        gone = payload.get("repositories_removed", []) + (payload.get("repositories", []) if removed else [])
        for r in added:
            for repo in _repos_named(db, r["full_name"]):
                repo.installation_id = None if removed else inst_id
        for r in gone:
            for repo in _repos_named(db, r["full_name"]):
                repo.installation_id = None
        db.commit()
        return {"status": "ok"}

    if x_github_event == "pull_request":
        if payload.get("action") not in PR_ACTIONS:
            return {"status": "ignored", "reason": f"action {payload.get('action')}"}
        repos = _repos_named(db, payload["repository"]["full_name"])
        if not repos:
            return {"status": "ignored", "reason": "repository not registered in the dashboard"}
        repo, pr = repos[0], payload["pull_request"]
        if payload.get("installation"):
            repo.installation_id = payload["installation"]["id"]
        head_sha, base_sha = pr["head"]["sha"], pr["base"]["sha"]
        dup = db.scalar(select(Scan.id).where(
            Scan.repository_id == repo.id, Scan.trigger == ScanTrigger.pull_request,
            Scan.pr_number == pr["number"], Scan.commit_sha == head_sha, Scan.status != ScanStatus.failed))
        if dup:
            return {"status": "duplicate", "scan_id": dup}
        scan = Scan(repository_id=repo.id, trigger=ScanTrigger.pull_request, status=ScanStatus.pending,
                    pr_number=pr["number"], commit_sha=head_sha)
        db.add(scan)
        db.commit()
        background.add_task(run_pr_scan, scan.id, base_sha, head_sha)
        return {"status": "queued", "scan_id": scan.id}

    if x_github_event == "push":
        default = payload["repository"].get("default_branch")
        if payload.get("ref") != f"refs/heads/{default}":
            return {"status": "ignored", "reason": "not the default branch"}
        queued = []
        for repo in _repos_named(db, payload["repository"]["full_name"]):
            if _active_scan(db, repo.id):
                continue
            scan = Scan(repository_id=repo.id, trigger=ScanTrigger.push, status=ScanStatus.pending)
            db.add(scan)
            db.commit()
            background.add_task(run_scan, scan.id)
            queued.append(scan.id)
        return {"status": "queued" if queued else "ignored", "scan_ids": queued}

    return {"status": "ignored", "reason": f"event {x_github_event}"}
