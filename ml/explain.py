"""B3 - Explain every risk score with SHAP, and turn the explanation into advice.

For each file:
  * features      - the individual metrics that pushed its risk up (+) or down (-)
  * factors       - the same SHAP values summed into understandable groups
                    (Size, Complexity, Change activity, Bug history, ...). SHAP values add up
                    exactly, so a group's impact is the sum of its features' impacts. Grouping
                    also cancels odd signs between strongly related features (e.g. size vs
                    maintainability), which would otherwise confuse readers.
  * recommendation- concrete actions for the factors that raise the risk most

Impacts are in log-odds (the model's internal score): +0.5 roughly means "noticeably riskier".

    from ml.explain import RiskExplainer
    explainer = RiskExplainer.from_bundle(joblib.load("data/models/risk_model.joblib"))
    results = explainer.explain(features_df)   # one dict per row
"""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import shap

# ---------------------------------------------------------------------------
# Feature names people understand, and how features group into factors
# ---------------------------------------------------------------------------

FEATURE_INFO: dict[str, tuple[str, str]] = {
    # feature: (factor group, readable label)
    "loc": ("size", "Lines of code"),
    "sloc": ("size", "Source lines"),
    "comments": ("size", "Comment lines"),
    "comment_ratio": ("size", "Comments per source line"),
    "num_functions": ("size", "Number of functions"),
    "num_classes": ("size", "Number of classes"),
    "halstead_volume": ("size", "Halstead volume"),
    "total_complexity": ("complexity", "Total cyclomatic complexity"),
    "avg_complexity": ("complexity", "Average function complexity"),
    "max_complexity": ("complexity", "Most complex function"),
    "max_nesting_depth": ("complexity", "Deepest nesting"),
    "avg_function_length": ("complexity", "Average function length"),
    "max_function_length": ("complexity", "Longest function"),
    "max_params": ("complexity", "Most parameters in a function"),
    "maintainability": ("complexity", "Maintainability index"),
    "commit_count": ("change_activity", "Commits so far"),
    "churn": ("change_activity", "Lines changed so far"),
    "lines_added": ("change_activity", "Lines added so far"),
    "lines_deleted": ("change_activity", "Lines deleted so far"),
    "recent_commit_count": ("change_activity", "Commits in last 90 days"),
    "recent_churn": ("change_activity", "Lines changed in last 90 days"),
    "days_since_last_change": ("change_activity", "Days since last change"),
    "age_days": ("change_activity", "File age (days)"),
    "bug_fix_count": ("bug_history", "Past bug fixes"),
    "bug_fix_ratio": ("bug_history", "Share of commits that fixed bugs"),
    "num_developers": ("team", "Developers who changed it"),
    "top_author_share": ("team", "Main author's share of commits"),
    "fan_in": ("coupling", "Files that import it"),
    "fan_out": ("coupling", "Internal files it imports"),
    "coupling": ("coupling", "Coupling (fan-in + fan-out)"),
    "instability": ("coupling", "Instability"),
    "num_imports": ("coupling", "Import statements"),
    "has_test_file": ("tests", "Has a matching test file"),
    "test_importers": ("tests", "Test files that import it"),
    "duplication": ("duplication", "Duplicated lines (%)"),
    "msg_frustrated": ("commit_messages", "Frustrated commit messages (share)"),
    "msg_rushed": ("commit_messages", "Rushed-work commit messages (share)"),
    "msg_short": ("commit_messages", "Very short commit messages (share)"),
    "msg_revert": ("commit_messages", "Reverted commits (share)"),
    "msg_words": ("commit_messages", "Average commit message length"),
    "msg_late_night": ("commit_messages", "Late-night commits (share)"),
    "msg_weekend": ("commit_messages", "Weekend commits (share)"),
    "msg_hf_frustration": ("commit_messages", "Frustration in messages (AI emotion model)"),
}

FACTOR_LABELS = {
    "size": "Size", "complexity": "Complexity", "change_activity": "Change activity",
    "bug_history": "Bug history", "team": "Team / ownership", "coupling": "Coupling",
    "tests": "Tests", "duplication": "Duplication", "commit_messages": "Commit messages",
    "other": "Other",
}


def _fmt(v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "?"
    if isinstance(v, (int, np.integer)) or float(v).is_integer():
        return f"{int(v):,}"
    return f"{v:.2f}" if abs(v) < 10 else f"{v:,.0f}"


def _v(row: pd.Series, col: str) -> str:
    return _fmt(row.get(col))


MIN_ADVICE_RISK = 0.35  # below "medium" risk no action is recommended (same threshold as the backend)
MIN_FACTOR_IMPACT = 0.15


def _n(row: pd.Series, col: str) -> float:
    v = row.get(col)
    return 0.0 if v is None or pd.isna(v) else float(v)


# Advice only applies when the file's own numbers justify it (no "split this 86-line file").
ADVICE_APPLIES = {
    "complexity": lambda r: _n(r, "max_complexity") >= 10 or _n(r, "max_nesting_depth") >= 4,
    "size": lambda r: _n(r, "loc") >= 400,
    "change_activity": lambda r: _n(r, "commit_count") >= 30 or _n(r, "recent_commit_count") >= 3,
    "bug_history": lambda r: _n(r, "bug_fix_count") >= 3,
    "team": lambda r: _n(r, "num_developers") >= 5,
    "coupling": lambda r: _n(r, "fan_in") + _n(r, "fan_out") >= 8,
    "tests": lambda r: _n(r, "has_test_file") == 0 and _n(r, "test_importers") == 0,
    "duplication": lambda r: _n(r, "duplication") >= 5,
    "commit_messages": lambda r: (_n(r, "msg_hf_frustration") >= 0.1 or _n(r, "msg_frustrated") >= 0.05
                                  or _n(r, "msg_rushed") >= 0.05),
}

# Advice per factor, filled with the file's own numbers.
ADVICE = {
    "complexity": lambda r: (f"Break down complex code (most complex function: {_v(r, 'max_complexity')}, "
                             f"nesting depth {_v(r, 'max_nesting_depth')}) into smaller functions with early returns."),
    "size": lambda r: f"Split this {_v(r, 'loc')}-line file into smaller, focused modules.",
    "change_activity": lambda r: (f"It changes very often ({_v(r, 'commit_count')} commits, "
                                  f"{_v(r, 'recent_commit_count')} in the last 90 days): stabilise its interface "
                                  f"and add regression tests before the next change."),
    "bug_history": lambda r: (f"{_v(r, 'bug_fix_count')} past bug fixes: do a root-cause review and add tests "
                              f"around the fragile parts."),
    "team": lambda r: (f"{_v(r, 'num_developers')} different developers changed it: assign a code owner and "
                       f"require their review."),
    "coupling": lambda r: (f"Highly connected (imported by {_v(r, 'fan_in')} files, imports {_v(r, 'fan_out')}): "
                           f"hide it behind a smaller interface so changes don't ripple."),
    "tests": lambda r: "No dedicated tests found: add unit tests before changing it again.",
    "duplication": lambda r: f"{_v(r, 'duplication')}% of its lines are duplicated: extract the shared code.",
    "commit_messages": lambda r: ("Commit messages suggest rushed or frustrated work: plan time to clean it up "
                                  "properly instead of quick fixes."),
}


# ---------------------------------------------------------------------------
# SHAP
# ---------------------------------------------------------------------------


class RiskExplainer:
    def __init__(self, model, features: list[str], background: pd.DataFrame):
        self.model, self.features = model, features
        steps = model.steps if hasattr(model, "steps") else None
        final = steps[-1][1] if steps else model
        # Every preprocessing step (impute, log, scale) is per-feature, so SHAP values in the
        # transformed space belong 1:1 to the original features.
        self._prep = model[:-1] if steps and len(steps) > 1 else None
        bg = self._transform(background[features])

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if hasattr(final, "coef_"):
                masker = shap.maskers.Independent(bg, max_samples=len(bg))  # use every background row
                self._explainer, self._kind = shap.LinearExplainer(final, masker), "linear"
            elif hasattr(final, "feature_importances_"):
                self._explainer, self._kind = shap.TreeExplainer(final, bg), "tree"
            else:  # anything else (e.g. the ensemble): model-agnostic, slower
                f = lambda X: model.predict_proba(pd.DataFrame(X, columns=features))[:, 1]
                self._explainer = shap.Explainer(f, background[features].to_numpy())
                self._kind, self._prep = "agnostic", None

    @classmethod
    def from_bundle(cls, bundle: dict) -> "RiskExplainer":
        return cls(bundle["model"], bundle["features"], bundle["background"])

    def _transform(self, X: pd.DataFrame) -> np.ndarray:
        return self._prep.transform(X) if self._prep is not None else X.to_numpy(dtype=float)

    @property
    def base_value(self) -> float:
        ev = self._explainer.expected_value
        return float(np.ravel(ev)[-1])

    def shap_values(self, X: pd.DataFrame) -> pd.DataFrame:
        """SHAP value of every feature for every row (log-odds for linear/XGBoost models)."""
        X = X[self.features]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if self._kind == "agnostic":
                vals = self._explainer(X.to_numpy(dtype=float)).values
            else:
                vals = self._explainer.shap_values(self._transform(X))
        if isinstance(vals, list):  # older SHAP: one array per class
            vals = vals[1]
        vals = np.asarray(vals)
        if vals.ndim == 3:  # newer SHAP: (rows, features, classes)
            vals = vals[..., 1]
        return pd.DataFrame(vals, index=X.index, columns=self.features)

    def explain(
        self,
        X: pd.DataFrame,
        top_features: int = 6,
        max_advice: int = 2,
        risk: pd.Series | None = None,
        scale: float = 1.0,
        min_advice_risk: float = MIN_ADVICE_RISK,
    ) -> list[dict]:
        """`risk`: calibrated probabilities (B4); `scale`: the calibration slope, so impacts are
        in calibrated log-odds and still add up exactly (calibrated score = a*raw + b)."""
        sv = self.shap_values(X) * scale
        groups = pd.Series({f: FEATURE_INFO.get(f, ("other", f))[0] for f in self.features})
        factors = sv.T.groupby(groups).sum().T  # rows x factor groups
        if risk is None:
            risk = pd.Series(self.model.predict_proba(X[self.features])[:, 1], index=X.index)

        out = []
        for idx in sv.index:
            row, s = X.loc[idx], sv.loc[idx]
            top = s.reindex(s.abs().sort_values(ascending=False).index).head(top_features)
            features = [{
                "feature": f,
                "label": FEATURE_INFO.get(f, ("other", f))[1],
                "group": groups[f],
                "value": None if pd.isna(row[f]) else (float(row[f]) if not float(row[f]).is_integer() else int(row[f])),
                "impact": round(float(v), 3),
            } for f, v in top.items()]

            fac = factors.loc[idx].sort_values(ascending=False)
            factor_list = [{"factor": g, "label": FACTOR_LABELS.get(g, g), "impact": round(float(v), 3)}
                           for g, v in fac.items() if abs(v) >= 0.01]
            if risk[idx] < min_advice_risk:
                recommendation = "Low risk: no action needed right now."
            else:
                raising = [g for g, v in fac.items()
                           if v >= MIN_FACTOR_IMPACT and g in ADVICE and ADVICE_APPLIES[g](row)]
                advice = [ADVICE[g](row) for g in raising[:max_advice]]
                recommendation = " ".join(advice) if advice else (
                    "Several small factors add up: review it carefully and add tests when you change it.")
            out.append({
                "risk_score": round(float(risk[idx]), 3),
                "explanation": features,
                "factors": factor_list,
                "recommendation": recommendation,
            })
        return out

    def global_importance(self, X: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
        """Mean |SHAP| per feature and per factor over many files: what drives risk overall."""
        sv = self.shap_values(X)
        by_feature = sv.abs().mean().sort_values(ascending=False)
        groups = pd.Series({f: FEATURE_INFO.get(f, ("other", f))[0] for f in self.features})
        by_factor = sv.T.groupby(groups).sum().T.abs().mean().sort_values(ascending=False)
        return by_feature, by_factor
