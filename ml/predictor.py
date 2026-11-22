"""B4 - The packaged model: `predict(file_data)`.

    from ml.predictor import predict, RiskPredictor

    predict({"loc": 1184, "commit_count": 735, ...})        # one file  -> dict
    RiskPredictor.load().predict(scan_result.features)      # many files -> DataFrame

Every result has:
    risk_score      calibrated probability of needing a bug fix in the next 6 months (0..1)
    risk_level      low / medium / high / critical
    priority_rank   1 = look at this first (when predicting many files)
    explanation     top SHAP features  [{feature, label, group, value, impact}, ...]
    factors         SHAP grouped       [{factor, label, impact}, ...]
    recommendation  what to do about it

    python -m ml.predictor data/processed/psf__requests_latest_features.csv
"""

from __future__ import annotations

import argparse
import logging
import os
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from ml.explain import RiskExplainer
from pipeline.paths import DATA_DIR

# RISK_MODEL_PATH lets a container ship the model inside the image while data/ is a volume.
DEFAULT_MODEL = Path(os.environ.get("RISK_MODEL_PATH", DATA_DIR / "models" / "production.joblib"))
log = logging.getLogger(__name__)


class RiskPredictor:
    def __init__(self, bundle: dict):
        self.model = bundle["model"]
        self.features: list[str] = bundle["features"]
        self.version: str = bundle.get("version", bundle.get("name", "unknown"))
        cal = bundle.get("calibration", {"a": 1.0, "b": 0.0})
        self.a, self.b = float(cal["a"]), float(cal["b"])
        self.thresholds: dict[str, float] = bundle["thresholds"]
        self._background = bundle["background"]
        self._explainer: RiskExplainer | None = None  # built on first use (SHAP setup ~1s)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MODEL) -> "RiskPredictor":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"{path} not found - run `python -m ml.train` then `python -m ml.package`")
        return cls(joblib.load(path))

    # --- scoring -----------------------------------------------------------------

    def _prepare(self, data: pd.DataFrame) -> pd.DataFrame:
        missing = [f for f in self.features if f not in data.columns]
        if missing:
            log.warning("Missing features filled as unknown: %s", ", ".join(missing))
        X = data.reindex(columns=self.features).apply(pd.to_numeric, errors="coerce")
        return X.astype(float)

    def _raw(self, X: pd.DataFrame) -> np.ndarray:
        if hasattr(self.model, "decision_function"):
            return self.model.decision_function(X)
        p = np.clip(self.model.predict_proba(X)[:, 1], 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def _calibrated(self, X: pd.DataFrame) -> np.ndarray:
        return 1 / (1 + np.exp(-(self.a * self._raw(X) + self.b)))

    def risk_scores(self, data: pd.DataFrame) -> np.ndarray:
        """Calibrated probabilities only (fast, no explanations)."""
        if data.empty:
            return np.array([], dtype=float)
        return self._calibrated(self._prepare(data))

    def risk_level(self, score: float) -> str:
        t = self.thresholds
        if score >= t["critical"]:
            return "critical"
        if score >= t["high"]:
            return "high"
        if score >= t["medium"]:
            return "medium"
        return "low"

    # --- full prediction ----------------------------------------------------------

    @property
    def explainer(self) -> RiskExplainer:
        if self._explainer is None:
            self._explainer = RiskExplainer(self.model, self.features, self._background)
        return self._explainer

    def predict(self, data: pd.DataFrame, explain: bool = True) -> pd.DataFrame:
        if data.empty:  # scikit-learn refuses 0 rows; nothing to score is a valid answer
            cols = ["file_path", "risk_score", "risk_level", "priority_rank", "model_version"]
            if explain:
                cols[4:4] = ["explanation", "factors", "recommendation"]
            return pd.DataFrame(columns=cols)
        X = self._prepare(data).set_axis(data.index)
        scores = pd.Series(self._calibrated(X), index=data.index)
        out = pd.DataFrame(index=data.index)
        if "file_path" in data.columns:
            out["file_path"] = data["file_path"]
        out["risk_score"] = scores.round(4)
        out["risk_level"] = scores.map(self.risk_level)
        out["priority_rank"] = scores.rank(ascending=False, method="first").astype(int)
        if explain:
            details = self.explainer.explain(X, risk=scores, scale=self.a,
                                             min_advice_risk=self.thresholds["medium"])
            out["explanation"] = [d["explanation"] for d in details]
            out["factors"] = [d["factors"] for d in details]
            out["recommendation"] = [d["recommendation"] for d in details]
        out["model_version"] = self.version
        return out.sort_values("priority_rank")


@lru_cache(maxsize=1)
def _default_predictor() -> RiskPredictor:
    return RiskPredictor.load()


def predict(file_data: dict | pd.DataFrame, explain: bool = True) -> dict | pd.DataFrame:
    """One file (dict of features) -> dict; a DataFrame of files -> DataFrame."""
    predictor = _default_predictor()
    if isinstance(file_data, dict):
        return predictor.predict(pd.DataFrame([file_data]), explain=explain).iloc[0].to_dict()
    return predictor.predict(file_data, explain=explain)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score files from a features CSV (pipeline scan output).")
    ap.add_argument("features_csv")
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()
    p = RiskPredictor.load()
    res = p.predict(pd.read_csv(args.features_csv))
    print(f"model {p.version} | levels: {res['risk_level'].value_counts().to_dict()}\n")
    for _, r in res.head(args.top).iterrows():
        factors = ", ".join(f"{f['label']} {f['impact']:+.2f}" for f in r["factors"][:3])
        print(f"#{r.priority_rank} {r.file_path}  {r.risk_score:.2f} {r.risk_level.upper()}\n"
              f"   why: {factors}\n   do:  {r.recommendation}")


if __name__ == "__main__":
    main()
