"""Fill the local database with realistic fake data so the frontend (Member 4) can be built
before the real scanner/model are connected.

    python -m app.seed_demo

Creates user  demo@example.com / demo-password  with one repo, 4 completed scans
(risk trending over time), per-file metrics, SHAP explanations and commit history.
Running it again resets the demo user's data. Never run against production.
"""

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal, init_db
from app.models import CommitHistory, FileAnalysis, Repository, Scan, ScanStatus, User
from app.services.risk import risk_level_for

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-password"

FILES = [
    "src/requests/models.py", "src/requests/sessions.py", "src/requests/adapters.py",
    "src/requests/utils.py", "src/requests/auth.py", "src/requests/cookies.py",
    "src/requests/structures.py", "src/requests/exceptions.py", "src/requests/api.py",
    "src/requests/hooks.py", "src/requests/status_codes.py", "src/requests/compat.py",
    "src/requests/help.py", "src/requests/certs.py", "src/requests/_internal_utils.py",
    "src/requests/packages.py",
]
AUTHORS = ["alice", "bob", "carol", "dave", "erin", "frank"]
RECOMMENDATIONS = {
    "churn": "Changes very often - stabilise its interface and add regression tests.",
    "complexity": "Very complex - split large functions into smaller, testable units.",
    "bug_fix_count": "Frequent bug fixes - review the design and raise test coverage.",
    "num_developers": "Many contributors - assign a code owner and document conventions.",
    "test_coverage": "Low test coverage - add unit tests before the next change.",
}


def _file_result(rng: random.Random, path: str, base: float, drift: float) -> FileAnalysis:
    score = min(0.99, max(0.02, base + drift + rng.uniform(-0.05, 0.05)))
    m = dict(
        commit_count=int(20 + 300 * score + rng.randint(0, 30)),
        churn=int(500 + 9000 * score + rng.randint(0, 800)),
        num_developers=int(1 + 14 * score + rng.randint(0, 2)),
        bug_fix_count=int(40 * score + rng.randint(0, 5)),
        complexity=round(2 + 25 * score + rng.uniform(0, 3), 1),
        loc=int(80 + 1200 * score + rng.randint(0, 100)),
        coupling=round(0.1 + 0.7 * score, 2),
        duplication=round(1 + 12 * score, 1),
        test_coverage=round(max(5.0, 95 - 70 * score + rng.uniform(-5, 5)), 1),
        maintainability=round(max(5.0, 90 - 60 * score), 1),
    )
    # Fake SHAP: bigger metric -> bigger positive impact; coverage pulls risk down.
    impacts = {
        "churn": m["churn"] / 10000 * 0.3,
        "complexity": m["complexity"] / 30 * 0.25,
        "bug_fix_count": m["bug_fix_count"] / 45 * 0.25,
        "num_developers": m["num_developers"] / 16 * 0.15,
        "test_coverage": -(m["test_coverage"] / 100) * 0.2,
    }
    explanation = sorted(
        ({"feature": k, "value": m[k], "impact": round(v, 3)} for k, v in impacts.items()),
        key=lambda e: abs(e["impact"]),
        reverse=True,
    )
    top = next(e["feature"] for e in explanation if e["impact"] > 0)
    if m["test_coverage"] < 40:
        top = "test_coverage"
    return FileAnalysis(
        file_path=path, risk_score=round(score, 3), risk_level=risk_level_for(score),
        explanation=explanation, recommendation=RECOMMENDATIONS[top], **m,
    )


def seed() -> None:
    init_db()
    rng = random.Random(42)  # same data every run
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        old = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if old:
            db.delete(old)
            db.commit()

        user = User(email=DEMO_EMAIL, hashed_password=hash_password(DEMO_PASSWORD), github_username="demo")
        repo = Repository(owner=user, full_name="psf/requests", url="https://github.com/psf/requests")

        bases = {f: rng.uniform(0.05, 0.9) for f in FILES}
        for i in range(4):  # 4 monthly scans, risk slowly creeping up (technical debt!)
            scan = Scan(
                repository=repo, status=ScanStatus.completed, model_version="demo-v1",
                commit_sha=f"{rng.getrandbits(160):040x}",
                created_at=now - timedelta(days=30 * (3 - i)),
                finished_at=now - timedelta(days=30 * (3 - i)) + timedelta(minutes=3),
            )
            files = sorted(
                (_file_result(rng, f, b, drift=0.03 * i) for f, b in bases.items()),
                key=lambda fa: fa.risk_score, reverse=True,
            )
            for rank, fa in enumerate(files, start=1):
                fa.priority_rank = rank
            scan.files = files
            scan.overall_risk = round(sum(f.risk_score for f in files) / len(files), 3)

        for f, b in bases.items():
            for _ in range(int(5 + 25 * b)):
                bug = rng.random() < b * 0.5
                repo.commits.append(CommitHistory(
                    commit_sha=f"{rng.getrandbits(160):040x}",
                    commit_date=now - timedelta(days=rng.randint(0, 365)),
                    author=rng.choice(AUTHORS), file_path=f, change_type="MODIFY",
                    lines_added=rng.randint(1, 200), lines_deleted=rng.randint(0, 120),
                    commit_message=("Fix " if bug else "Update ") + f.rsplit("/", 1)[-1],
                    is_bug_fix=bug,
                ))
        # Add last: the whole user -> repo -> scans/files/commits tree is saved via cascade.
        db.add(user)
        db.commit()
        print(f"Seeded demo data. Log in as {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    seed()
