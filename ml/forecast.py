"""B4 - Projected technical debt over time (data for the dashboard trend chart).

Debt measures per snapshot (every file scored by the calibrated model):
  expected_bug_prone_files  sum of risk scores = how many files the model expects to need bug
                            fixes in the next 6 months
  risk_weighted_kloc        sum of risk x size / 1000 = how much code sits in risky files
  critical/high/medium/low  number of files per level

Projection: a straight-line trend through the last few snapshots, extended 6/12/18 months,
with a 95% band from how far past points scattered around that line.

    python -m ml.forecast pallets__flask
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from ml.predictor import RiskPredictor
from pipeline.paths import DATA_DIR

DATASET = DATA_DIR / "processed" / "dataset.csv"
PROCESSED = DATA_DIR / "processed"
MEASURES = ["expected_bug_prone_files", "risk_weighted_kloc"]


def debt_history(predictor: RiskPredictor, snapshots: pd.DataFrame) -> pd.DataFrame:
    """One row per snapshot date with the debt measures."""
    df = snapshots.copy()
    df["risk"] = predictor.risk_scores(df)
    df["level"] = df["risk"].map(predictor.risk_level)
    df["weighted_loc"] = df["risk"] * df["loc"].fillna(0)
    g = df.groupby("snapshot_date")
    out = pd.DataFrame({
        "files": g.size(),
        "expected_bug_prone_files": g["risk"].sum().round(2),
        "risk_weighted_kloc": (g["weighted_loc"].sum() / 1000).round(2),
        "avg_risk": g["risk"].mean().round(3),
    })
    levels = df.pivot_table(index="snapshot_date", columns="level", values="risk", aggfunc="size", fill_value=0)
    for lvl in ("critical", "high", "medium", "low"):
        out[lvl] = levels.get(lvl, 0)
    return out.reset_index().rename(columns={"snapshot_date": "date"})


def project(history: pd.DataFrame, months_ahead=(6, 12, 18), window: int = 6) -> tuple[pd.DataFrame, dict]:
    """Linear trend through the last `window` points, extended into the future."""
    recent = history.tail(window)
    last = history["date"].max()
    t = (recent["date"] - last).dt.days.to_numpy() / 365.25  # years, 0 = latest point
    future_dates = [last + pd.DateOffset(months=m) for m in months_ahead]
    tf = np.array([(d - last).days / 365.25 for d in future_dates])

    rows = {"date": future_dates}
    trend = {}
    for col in MEASURES:
        y = recent[col].to_numpy(dtype=float)
        if len(y) >= 3:
            slope, intercept = np.polyfit(t, y, 1)
            resid = y - (slope * t + intercept)
            band = 1.96 * resid.std(ddof=2) if len(y) > 2 else 0.0
        else:  # too little history: flat line
            slope, intercept, band = 0.0, float(y[-1]), 0.0
        pred = np.clip(slope * tf + intercept, 0, None)
        rows[col] = pred.round(2)
        rows[f"{col}_low"] = np.clip(pred - band, 0, None).round(2)
        rows[f"{col}_high"] = (pred + band).round(2)
        level = max(abs(float(y.mean())), 1e-9)
        trend[col] = {
            "per_year": round(float(slope), 3),
            "direction": "rising" if slope > 0.05 * level else "falling" if slope < -0.05 * level else "flat",
        }
    return pd.DataFrame(rows), trend


def load_snapshots(repo: str) -> pd.DataFrame:
    """Historical snapshots (A3 dataset) + today's scan (A4) for one repo."""
    hist = pd.read_csv(DATASET, parse_dates=["snapshot_date"])
    hist = hist[hist["repo"] == repo]
    latest_file = PROCESSED / f"{repo}_latest_features.csv"
    if latest_file.exists():
        latest = pd.read_csv(latest_file, parse_dates=["snapshot_date"])
        hist = pd.concat([hist, latest], ignore_index=True)
    if hist.empty:
        raise ValueError(f"No data for {repo} - run `python -m pipeline.run refresh` first")
    return hist


def debt_timeline(repo: str, predictor: RiskPredictor | None = None) -> dict:
    """Everything the 'Projected Technical Debt Over Time' chart needs, as JSON-ready dict."""
    predictor = predictor or RiskPredictor.load()
    history = debt_history(predictor, load_snapshots(repo))
    projection, trend = project(history)
    as_records = lambda d: json.loads(d.assign(date=d["date"].dt.strftime("%Y-%m-%d")).to_json(orient="records"))
    return {
        "repo": repo,
        "model_version": predictor.version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "history": as_records(history),
        "projection": as_records(projection),
        "trend": trend,
    }


def backtest(predictor: RiskPredictor, dataset: pd.DataFrame, min_history: int = 4) -> pd.DataFrame:
    """At each past snapshot, compare with the bug-prone files that REALLY followed:
    (a) the model's own expectation for that snapshot, (b) the trend projected from earlier
    snapshots only, (c) naive: same as the previous snapshot's real count."""
    rows = []
    for repo, g in dataset.groupby("repo"):
        hist = debt_history(predictor, g)
        actual = g.groupby("snapshot_date")["label_bug_prone"].sum().reindex(hist["date"]).to_numpy()
        for i in range(min_history, len(hist)):
            proj, _ = project(hist.iloc[:i], months_ahead=(6,))
            rows.append({"repo": repo, "date": hist["date"].iloc[i], "actual": actual[i],
                         "model": hist["expected_bug_prone_files"].iloc[i],
                         "trend": proj["expected_bug_prone_files"].iloc[0],
                         "naive_last": actual[i - 1]})
    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Technical-debt history and projection for a repo.")
    ap.add_argument("repo", help="repo folder name, e.g. pallets__flask")
    ap.add_argument("--json", action="store_true", help="print the full JSON")
    args = ap.parse_args()
    tl = debt_timeline(args.repo)
    if args.json:
        print(json.dumps(tl, indent=2))
        return
    h = pd.DataFrame(tl["history"]).tail(6)
    print(f"{args.repo} - last snapshots:\n{h[['date', 'files', 'expected_bug_prone_files', 'risk_weighted_kloc', 'critical', 'high']].to_string(index=False)}")
    print(f"\nProjection:\n{pd.DataFrame(tl['projection']).to_string(index=False)}")
    print(f"\nTrend: {tl['trend']}")


if __name__ == "__main__":
    main()
