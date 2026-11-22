"""B2 - Train and compare risk models with a leak-free, time-based evaluation.

Models
  * baselines       - no learning: rank files by size (loc) or recent activity
  * logistic        - logistic regression on log-scaled features (simple, interpretable)
  * random_forest   - scikit-learn RandomForest
  * xgboost         - gradient-boosted trees

Evaluation (what matters for a "fix these first" list, not plain accuracy)
  * ROC-AUC          - how well risky files are ranked above safe ones (0.5 = random)
  * PR-AUC           - average precision; honest under class imbalance (random = positive rate)
  * recall@20%       - share of future bug-prone files caught by reviewing the top 20% of files
  * precision@5      - of the 5 files flagged first in each repo snapshot, how many really got bugs

Time rules
  * test     = snapshots from TEST_START on - never used for training or tuning
  * training = snapshots whose label window ends before TEST_START (no peeking at the future)
  * tuning   = same rule inside the training years (expanding-window validation folds)

    python -m ml.train
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import RandomizedSearchCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import FunctionTransformer, StandardScaler
from xgboost import XGBClassifier

from ml.models import RankAverageEnsemble, log1p_nonneg
from pipeline.dataset import LABEL_COLS, META_COLS
from pipeline.paths import DATA_DIR

DATASET = DATA_DIR / "processed" / "dataset.csv"
MODEL_DIR = DATA_DIR / "models"
TEST_START = pd.Timestamp("2023-01-01", tz="UTC")
VALIDATION_YEARS = [2019, 2020, 2021, 2022]
TARGET = "label_bug_prone"
SEED = 42

# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------


def load_dataset(path: Path = DATASET) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["snapshot_date"])
    for col in df.columns:
        if df[col].dtype == bool:
            df[col] = df[col].astype(int)
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    cols = [c for c in df.columns if c not in META_COLS + LABEL_COLS]
    # Drop columns with a single value (e.g. is_test_file after filtering tests out).
    return [c for c in cols if df[c].nunique(dropna=True) > 1 and pd.api.types.is_numeric_dtype(df[c])]


def label_end(df: pd.DataFrame) -> pd.Series:
    return df["snapshot_date"] + pd.to_timedelta(df["horizon_months"] * 30.44, unit="D")


def time_split(df: pd.DataFrame, test_start: pd.Timestamp = TEST_START):
    test = df["snapshot_date"] >= test_start
    train = label_end(df) <= test_start
    return df[train], df[test]


def validation_folds(train: pd.DataFrame) -> list[tuple[np.ndarray, np.ndarray]]:
    """Expanding window: validate on year Y, train only on snapshots whose labels end before Y."""
    folds = []
    pos = np.arange(len(train))
    ends = label_end(train).to_numpy()
    dates = train["snapshot_date"]
    for year in VALIDATION_YEARS:
        start = pd.Timestamp(f"{year}-01-01", tz="UTC")
        val = ((dates >= start) & (dates < start + pd.DateOffset(years=1))).to_numpy()
        tr = ends <= start
        if val.any() and tr.any() and train[TARGET].to_numpy()[val].sum() > 0:
            folds.append((pos[tr], pos[val]))
    return folds


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def _per_snapshot(df: pd.DataFrame, score: np.ndarray, fn) -> float:
    vals = []
    for _, g in df.assign(_score=score).groupby(["repo", "snapshot_date"]):
        if g[TARGET].sum() > 0:
            vals.append(fn(g.sort_values("_score", ascending=False)))
    return float(np.mean(vals)) if vals else float("nan")


def evaluate(df: pd.DataFrame, score: np.ndarray) -> dict[str, float]:
    y = df[TARGET].to_numpy()

    def recall_at_20(g):
        k = max(1, int(np.ceil(0.2 * len(g))))
        return g[TARGET].iloc[:k].sum() / g[TARGET].sum()

    def recall_at_20_loc(g):
        # Effort-aware: review files in score order until 20% of the repo's lines are read.
        within = g["loc"].cumsum() <= 0.2 * g["loc"].sum()
        return g.loc[within, TARGET].sum() / g[TARGET].sum()

    return {
        "roc_auc": round(roc_auc_score(y, score), 3),
        "pr_auc": round(average_precision_score(y, score), 3),
        "recall_at_20pct": round(_per_snapshot(df, score, recall_at_20), 3),
        "recall_at_20pct_loc": round(_per_snapshot(df, score, recall_at_20_loc), 3),
        "precision_at_5": round(_per_snapshot(df, score, lambda g: g[TARGET].iloc[:5].mean()), 3),
    }


def bootstrap_ci(df: pd.DataFrame, score: np.ndarray, n: int = 500) -> dict[str, str]:
    """95% interval for ROC-AUC / PR-AUC, resampling whole repo snapshots (rows within a
    snapshot are related, so resampling single rows would be over-optimistic)."""
    rng = np.random.default_rng(SEED)
    keys = df[["repo", "snapshot_date"]].astype(str).agg("|".join, axis=1).to_numpy()
    groups = {k: np.flatnonzero(keys == k) for k in np.unique(keys)}
    names = list(groups)
    y = df[TARGET].to_numpy()
    roc, pr = [], []
    for _ in range(n):
        idx = np.concatenate([groups[names[i]] for i in rng.integers(0, len(names), len(names))])
        if 0 < y[idx].sum() < len(idx):
            roc.append(roc_auc_score(y[idx], score[idx]))
            pr.append(average_precision_score(y[idx], score[idx]))
    q = lambda v: f"{np.percentile(v, 2.5):.2f}-{np.percentile(v, 97.5):.2f}"
    return {"roc_auc_95ci": q(roc), "pr_auc_95ci": q(pr)}




# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def candidate_models(pos_weight: float) -> dict[str, tuple[object, dict]]:
    """name -> (estimator, hyper-parameter search space)."""
    return {
        "logistic": (
            make_pipeline(
                SimpleImputer(strategy="median"),
                FunctionTransformer(log1p_nonneg),  # counts/sizes are heavily skewed
                StandardScaler(),
                LogisticRegression(class_weight="balanced", max_iter=5000),
            ),
            {"logisticregression__C": np.logspace(-3, 1, 20)},
        ),
        "random_forest": (
            make_pipeline(
                SimpleImputer(strategy="median"),
                RandomForestClassifier(n_estimators=400, class_weight="balanced_subsample",
                                       random_state=SEED, n_jobs=-1),
            ),
            {
                "randomforestclassifier__max_depth": [3, 4, 6, 8, 12, None],
                "randomforestclassifier__min_samples_leaf": [1, 3, 5, 10, 20],
                "randomforestclassifier__max_features": ["sqrt", 0.3, 0.5],
            },
        ),
        "xgboost": (
            # XGBoost handles missing values (NaN) natively - no imputer needed.
            XGBClassifier(n_estimators=300, eval_metric="logloss", random_state=SEED, n_jobs=-1),
            {
                "max_depth": [2, 3, 4, 5, 6],
                "learning_rate": [0.01, 0.03, 0.05, 0.1],
                "n_estimators": [100, 200, 300, 500],
                "min_child_weight": [1, 3, 5, 10],
                "subsample": [0.6, 0.8, 1.0],
                "colsample_bytree": [0.5, 0.7, 1.0],
                "reg_lambda": [0.1, 1, 5, 10],
                "scale_pos_weight": [1, pos_weight],
            },
        ),
    }


def tune(name, estimator, space, X, y, folds, n_iter: int):
    n_iter = min(n_iter, int(np.prod([len(v) for v in space.values()])))
    search = RandomizedSearchCV(estimator, space, n_iter=n_iter, cv=folds, scoring="average_precision",
                                random_state=SEED, n_jobs=1, refit=True)
    search.fit(X, y)
    return search


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    ap = argparse.ArgumentParser(description="Train and compare code-risk models.")
    ap.add_argument("--iter", type=int, default=25, help="random-search trials per model")
    args = ap.parse_args()
    started = time.perf_counter()

    df = load_dataset()
    feats = feature_columns(df)
    train, test = time_split(df)
    folds = validation_folds(train)
    X_tr, y_tr, X_te = train[feats], train[TARGET].to_numpy(), test[feats]
    print(f"{len(feats)} features | train {len(train)} rows ({y_tr.mean():.1%} bug-prone, snapshots "
          f"{train.snapshot_date.min():%Y-%m}..{train.snapshot_date.max():%Y-%m}) | test {len(test)} rows "
          f"({test[TARGET].mean():.1%}, {test.snapshot_date.min():%Y-%m}..) | {len(folds)} validation folds\n")

    results, fitted = {}, {}
    for base in ("loc", "recent_commit_count"):
        results[f"baseline: {base}"] = {"cv_pr_auc": None, "train_roc_auc": None,
                                        **evaluate(test, test[base].to_numpy())}

    pos_weight = round((1 - y_tr.mean()) / y_tr.mean(), 2)
    for name, (est, space) in candidate_models(pos_weight).items():
        t = time.perf_counter()
        search = tune(name, est, space, X_tr, y_tr, folds, args.iter)
        model = search.best_estimator_
        fitted[name] = (model, search.best_params_)
        results[name] = {
            "cv_pr_auc": round(search.best_score_, 3),
            "train_roc_auc": round(roc_auc_score(y_tr, model.predict_proba(X_tr)[:, 1]), 3),
            **evaluate(test, model.predict_proba(X_te)[:, 1]),
        }
        print(f"  tuned {name:<14} in {time.perf_counter() - t:5.1f}s  best={search.best_params_}")

    # Ensemble of the two models that generalised best; scored on the same validation folds.
    members = [fitted["logistic"][0], fitted["random_forest"][0]]
    cv = [average_precision_score(y_tr[va], RankAverageEnsemble(members).fit(X_tr.iloc[tr], y_tr[tr])
                                  .predict_proba(X_tr.iloc[va])[:, 1]) for tr, va in folds]
    ens = RankAverageEnsemble(members).fit(X_tr, y_tr)
    fitted["ensemble"] = (ens, {"members": "logistic + random_forest (rank average)"})
    results["ensemble"] = {
        "cv_pr_auc": round(float(np.mean(cv)), 3),
        "train_roc_auc": round(roc_auc_score(y_tr, ens.predict_proba(X_tr)[:, 1]), 3),
        **evaluate(test, ens.predict_proba(X_te)[:, 1]),
    }

    for name in results:
        score = (test[name.split(": ")[1]].to_numpy() if name.startswith("baseline")
                 else fitted[name][0].predict_proba(X_te)[:, 1])
        results[name].update(bootstrap_ci(test, score))

    table = pd.DataFrame(results).T
    print(f"\nTest set ({TEST_START:%Y-%m} onwards, positive rate {test[TARGET].mean():.3f}):")
    pd.set_option("display.width", 250)
    print(table.to_string())

    # Pick by validation score only - the test set must not influence the choice.
    best = max(fitted, key=lambda n: results[n]["cv_pr_auc"])
    print(f"\nSelected by validation PR-AUC: {best}")

    # Generalisation to a repository the model has never seen (how the product is used).
    print("\nLeave-one-repo-out (train on 3 repos, test on the 4th, same time split):")
    model, params = fitted[best]
    lor = {}
    for repo in sorted(df["repo"].unique()):
        tr = train[train["repo"] != repo]
        te = test[test["repo"] == repo]
        if te[TARGET].sum() == 0:
            continue
        m = clone(model).fit(tr[feats], tr[TARGET])  # same hyper-parameters, fresh fit
        lor[repo] = evaluate(te, m.predict_proba(te[feats])[:, 1])
    print(pd.DataFrame(lor).T.to_string())

    # Feature importance of the selected model (SHAP explanations come in B3).
    est = model.steps[-1][1] if hasattr(model, "steps") else model
    if hasattr(est, "feature_importances_"):
        imp = pd.Series(est.feature_importances_, index=feats).sort_values(ascending=False)
        print("\nTop 10 features:", ", ".join(f"{k} {v:.3f}" for k, v in imp.head(10).items()))

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    # SHAP (B3) compares each file with a "typical" file: a sample of the training rows.
    background = X_tr.sample(min(200, len(X_tr)), random_state=SEED)
    joblib.dump({"model": model, "features": feats, "name": best, "params": params,
                 "background": background}, MODEL_DIR / "risk_model.joblib")
    report = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "selected_model": best,
        "params": {k: (v.item() if hasattr(v, "item") else v) for k, v in params.items()},
        "features": feats,
        "test_start": str(TEST_START.date()),
        "train_rows": len(train), "test_rows": len(test),
        "results": results, "leave_one_repo_out": lor,
    }
    (MODEL_DIR / "report.json").write_text(json.dumps(report, indent=2, default=str))
    print(f"\nSaved {MODEL_DIR / 'risk_model.joblib'} and report.json ({time.perf_counter() - started:.0f}s)")


if __name__ == "__main__":
    main()
