"""C2 - Pull-request review: score the files a PR changes and comment the result on GitHub.

    webhook "pull_request opened/synchronize" -> Scan(trigger=pull_request) -> run_pr_scan()

For every Python file the PR adds or modifies:
  risk at the PR head vs risk on the base branch -> shows whether the PR makes it riskier
The report is stored on the scan (report_markdown) and posted/updated as ONE PR comment.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import insert, select

from app.config import settings
from app.db.session import SessionLocal
from app.models import FileAnalysis, Scan, ScanStatus, ScanTrigger
from app.services.analysis import _file_rows, describe_error, get_predictor  # also puts pipeline/ml on sys.path
from app.services.github_app import GitHubNotConfigured, get_client

log = logging.getLogger(__name__)

MARKER = "<!-- code-risk-predictor -->"
LEVEL_ICON = {"critical": "🔴 Critical", "high": "🟠 High", "medium": "🟡 Medium", "low": "🟢 Low"}
MAX_ROWS = 15


def _factors(f: list[dict], n: int = 2) -> str:
    up = [x for x in f if x["impact"] > 0][:n]
    return ", ".join(f"{x['label']} +{x['impact']:.2f}" for x in up) or "–"


def build_report(head: pd.DataFrame, base: pd.DataFrame, pr_number: int, model_version: str,
                 repo_id: int, scan_id: int) -> str:
    """Markdown for the PR comment. `head` = predictions with explanations for changed files,
    `base` = risk_score of the same paths on the base branch (missing = new file)."""
    lines = [MARKER, "## 🔍 Code risk report", ""]
    if head.empty:
        lines += ["This pull request doesn't change any Python source files, so there is nothing to score.", ""]
    else:
        counts = head["risk_level"].value_counts()
        summary = " · ".join(f"{counts[k]} {k}" for k in ("critical", "high", "medium", "low") if k in counts)
        lines += [f"**{len(head)} Python file(s) changed** — {summary}", "",
                  "| File | Risk | Change vs base | Main factors |", "|---|---|---|---|"]
        base_risk = dict(zip(base["path"], base["risk_score"])) if not base.empty else {}
        for _, r in head.head(MAX_ROWS).iterrows():
            before = base_risk.get(r["path"])
            if before is None:
                change = "new file"
            else:
                d = r["risk_score"] - before
                # Arrow whenever the change is visible at 2 decimals (>= 0.005 rounds to 0.01).
                change = (f"▲ +{d:.2f}" if d >= 0.005 else f"▼ {d:.2f}" if d <= -0.005 else "≈ same") + f" (was {before:.2f})"
            lines.append(f"| `{r['path']}` | **{r['risk_score']:.2f}** {LEVEL_ICON[r['risk_level']]} | {change} "
                         f"| {_factors(r['factors'])} |")
        if len(head) > MAX_ROWS:
            lines.append(f"| … {len(head) - MAX_ROWS} more file(s) | | | |")
        advice = [(r["path"], r["recommendation"]) for _, r in head.iterrows() if r["risk_level"] != "low"]
        if advice:
            lines += ["", "<details><summary><b>Recommendations</b></summary>", ""]
            lines += [f"- **`{p}`** — {text}" for p, text in advice[:MAX_ROWS]]
            lines += ["", "</details>"]
    lines += ["", f"<sub>Risk = estimated chance the file needs a bug fix within 6 months "
                  f"(model `{model_version}`). [Open dashboard]({settings.dashboard_url}/repos/{repo_id}/scans/{scan_id})</sub>"]
    return "\n".join(lines)


def _previous_comment_id(db, repo_id: int, pr_number: int, scan_id: int) -> int | None:
    return db.scalar(
        select(Scan.github_comment_id)
        .where(Scan.repository_id == repo_id, Scan.trigger == ScanTrigger.pull_request,
               Scan.pr_number == pr_number, Scan.github_comment_id.is_not(None), Scan.id != scan_id)
        .order_by(Scan.id.desc()).limit(1)
    )


def run_pr_scan(scan_id: int, base_sha: str, head_sha: str | None = None) -> None:
    """Background job. Never raises: failures are stored on the scan."""
    with SessionLocal() as db:
        scan = db.get(Scan, scan_id)
        if scan is None:
            return
        repo = scan.repository
        scan.status = ScanStatus.running
        db.commit()
        try:
            from pipeline.scanner import changed_source_files, fetch_pull_request, scan_repository

            predictor = get_predictor()
            repo_path, fetched_head = fetch_pull_request(repo.url, scan.pr_number)
            head_sha = head_sha or fetched_head
            changed = set(changed_source_files(repo_path, base_sha, head_sha))

            head_pred = base_pred = pd.DataFrame()
            if changed:
                # The local path skips another `git pull`; the commit cache is shared.
                head_feat = scan_repository(str(repo_path), rev=head_sha).features
                head_feat = head_feat[head_feat["path_at_snapshot"].isin(changed)]
                if not head_feat.empty:
                    head_pred = predictor.predict(head_feat).assign(path=head_feat["path_at_snapshot"])
                    db.execute(insert(FileAnalysis), _file_rows(head_feat, head_pred, scan.id, with_details=True))
                base_feat = scan_repository(str(repo_path), rev=base_sha).features
                base_feat = base_feat[base_feat["path_at_snapshot"].isin(changed)]
                if not base_feat.empty:
                    base_pred = predictor.predict(base_feat, explain=False).assign(path=base_feat["path_at_snapshot"])

            report = build_report(head_pred, base_pred, scan.pr_number, predictor.version, repo.id, scan.id)
            scan.report_markdown = report
            scan.commit_sha = head_sha
            scan.model_version = predictor.version
            scan.overall_risk = round(float(head_pred["risk_score"].mean()), 4) if len(head_pred) else None

            client = get_client()
            if client.configured:
                try:
                    scan.github_comment_id = client.upsert_pr_comment(
                        repo.full_name, scan.pr_number, report, repo.installation_id,
                        _previous_comment_id(db, repo.id, scan.pr_number, scan.id))
                except GitHubNotConfigured as e:
                    scan.error_message = f"Report not posted: {e}"
                except Exception as e:  # analysis worked; only the comment failed
                    log.exception("Posting PR comment failed")
                    scan.error_message = f"Report not posted to GitHub: {type(e).__name__}: {e}"[:1000]
            else:
                scan.error_message = "Report not posted: no GitHub App / token configured"

            scan.status = ScanStatus.completed
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()
            log.info("PR #%s of %s reviewed: %d changed files", scan.pr_number, repo.full_name, len(head_pred))
        except Exception as exc:
            db.rollback()
            log.exception("PR scan %s failed", scan_id)
            scan = db.get(Scan, scan_id)
            scan.status = ScanStatus.failed
            scan.error_message = describe_error(exc)
            scan.finished_at = datetime.now(timezone.utc)
            db.commit()
