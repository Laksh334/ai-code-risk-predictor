"""B4 - Calibrate the model and build the production bundle that predict() loads.

Why calibrate: the model was trained with balanced class weights, which inflates scores
(half of all files scored >= 0.35 while only ~14% really get bug fixes). Platt scaling maps
the model's raw score to a real probability: p = sigmoid(a * score + b).

Leak-free: the calibrator is fitted on *out-of-time* predictions - for each year Y a model
trained only on data whose labels end before Y predicts year Y.

Steps
  1. evaluate - calibrator fitted on training years only, checked on the 2023+ test set
  2. produce  - model refitted on ALL labelled snapshots (more, newer data for live use),
                calibrator fitted on out-of-time predictions 2016-2025, saved with thresholds

    python -m ml.package
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.linear_model import LogisticRegression

from ml.train import (MODEL_DIR, SEED, TARGET, VALIDATION_YEARS, evaluate, feature_columns,
                      label_end, load_dataset, time_split)

PRODUCTION = MODEL_DIR / "production.joblib"
# Calibrated-probability cut-offs for the four spec levels, chosen from what actually happened
# on the 2023+ test set (overall rate ~10%):
#   critical >= 0.35 -> ~40% got bug fixes (3-4x average, top ~3% of files)
#   high     >= 0.20 -> ~29%   medium >= 0.10 -> ~21%   low < 0.10 -> 2-10%
RISK_THRESHOLDS = {"critical": 0.35, "high": 0.20, "medium": 0.10}
PRODUCTION_YEARS = list(range(2016, 2026))


def raw_score(model, X: pd.DataFrame) -> np.ndarray:
    """The model's internal score (log-odds). Calibration is fitted on this."""
    if hasattr(model, "decision_function"):
        return model.decision_function(X)
    p = np.clip(model.predict_proba(X)[:, 1], 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def out_of_time_scores(template, df: pd.DataFrame, feats: list[str], years) -> tuple[np.ndarray, np.ndarray]:
    """For each year Y: fit on rows whose labels end before Y, score the snapshots of year Y."""
    scores, labels = [], []
    ends = label_end(df)
    for year in years:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        tr = df[ends <= start]
        va = df[(df["snapshot_date"] >= start) & (df["snapshot_date"] < start + pd.DateOffset(years=1))]
        if va.empty or tr[TARGET].nunique() < 2:
            continue
        m = clone(template).fit(tr[feats], tr[TARGET])
        scores.append(raw_score(m, va[feats]))
        labels.append(va[TARGET].to_numpy())
    return np.concatenate(scores), np.concatenate(labels)


def fit_platt(scores: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(scores.reshape(-1, 1), y)
    return float(lr.coef_[0][0]), float(lr.intercept_[0])


def calibrate(scores: np.ndarray, a: float, b: float) -> np.ndarray:
    return 1 / (1 + np.exp(-(a * scores + b)))


def calibration_report(y: np.ndarray, p: np.ndarray, bins: int = 5) -> dict:
    """Brier score (lower = better), average predicted vs actual rate, and per-bin check."""
    q = pd.qcut(pd.Series(p).rank(method="first"), bins, labels=False)
    table = pd.DataFrame({"p": p, "y": y, "bin": q}).groupby("bin").agg(
        predicted=("p", "mean"), actual=("y", "mean"), files=("y", "size"))
    ece = float((table["files"] * (table["predicted"] - table["actual"]).abs()).sum() / len(y))
    return {
        "brier": round(float(np.mean((p - y) ** 2)), 4),
        "mean_predicted": round(float(p.mean()), 3),
        "actual_rate": round(float(y.mean()), 3),
        "calibration_error": round(ece, 3),
        "bins": table.round(3).reset_index(drop=True).to_dict("records"),
    }


def level_counts(p: np.ndarray) -> dict[str, int]:
    t = RISK_THRESHOLDS
    return {
        "critical": int((p >= t["critical"]).sum()),
        "high": int(((p >= t["high"]) & (p < t["critical"])).sum()),
        "medium": int(((p >= t["medium"]) & (p < t["high"])).sum()),
        "low": int((p < t["medium"]).sum()),
    }


def main() -> None:
    eval_bundle = joblib.load(MODEL_DIR / "risk_model.joblib")  # from `python -m ml.train`
    template, feats = eval_bundle["model"], eval_bundle["features"]
    df = load_dataset()
    train, test = time_split(df)

    # 1. Evaluate calibration honestly: calibrator from training years, judged on 2023+.
    s_cal, y_cal = out_of_time_scores(template, train, feats, VALIDATION_YEARS)
    a, b = fit_platt(s_cal, y_cal)
    s_test, y_test = raw_score(template, test[feats]), test[TARGET].to_numpy()
    raw_p = template.predict_proba(test[feats])[:, 1]
    cal_p = calibrate(s_test, a, b)
    print(f"Calibration fitted on {len(y_cal)} out-of-time predictions (2019-2022): p = sigmoid({a:.3f}*score + {b:.3f})\n")
    before, after = calibration_report(y_test, raw_p), calibration_report(y_test, cal_p)
    for name, rep in (("raw (balanced weights)", before), ("calibrated", after)):
        print(f"{name:<24} brier {rep['brier']:.4f}  avg predicted {rep['mean_predicted']:.3f} "
              f"vs actual {rep['actual_rate']:.3f}  calibration error {rep['calibration_error']:.3f}")
    print("\nCalibrated, by score fifth (2023+ test set):")
    print(pd.DataFrame(after["bins"]).to_string(index=False))
    same_rank = evaluate(test, cal_p)["roc_auc"] == evaluate(test, raw_p)["roc_auc"]
    print(f"Ranking unchanged by calibration: {same_rank}")

    # Expected vs actual bug-prone files per repo snapshot (basis of the debt projection).
    per_snap = test.assign(p=cal_p).groupby(["repo", "snapshot_date"]).agg(
        expected=("p", "sum"), actual=(TARGET, "sum"))
    print(f"Expected vs actual bug-prone files per snapshot: total {per_snap.expected.sum():.0f} vs "
          f"{per_snap.actual.sum()}, correlation {per_snap.expected.corr(per_snap.actual):.2f}")
    print("Risk levels on the test set:", level_counts(cal_p))

    # 2. Production model: all labelled data, calibrator from out-of-time years 2016-2025.
    model = clone(template).fit(df[feats], df[TARGET])
    s_all, y_all = out_of_time_scores(template, df, feats, PRODUCTION_YEARS)
    pa, pb = fit_platt(s_all, y_all)
    version = f"{eval_bundle['name']}-{datetime.now(timezone.utc):%Y%m%d}"
    bundle = {
        "model": model, "features": feats, "name": eval_bundle["name"], "version": version,
        "calibration": {"a": pa, "b": pb}, "thresholds": RISK_THRESHOLDS,
        "background": df[feats].sample(min(200, len(df)), random_state=SEED),
        "trained_rows": len(df), "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    joblib.dump(bundle, PRODUCTION)
    (MODEL_DIR / "calibration_report.json").write_text(json.dumps(
        {"evaluation": {"a": a, "b": b, "raw": before, "calibrated": after},
         "production": {"a": pa, "b": pb, "rows": len(df), "version": version}}, indent=2))
    print(f"\nProduction model {version}: trained on {len(df)} rows, calibration "
          f"p = sigmoid({pa:.3f}*score + {pb:.3f}) from {len(y_all)} out-of-time predictions -> {PRODUCTION}")


if __name__ == "__main__":
    main()
