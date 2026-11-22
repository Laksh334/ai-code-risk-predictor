"""Building blocks of the saved models.

They live in their own module (not in ml/train.py) on purpose: a pickled model stores
*where* its functions/classes come from. Defined inside a script run with `python -m`,
that would be `__main__`, and the backend could never load the model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone


def log1p_nonneg(x):
    """log(1 + x) for skewed counts/sizes; negatives clipped to 0."""
    return np.log1p(np.clip(x, 0, None))


def _rank01(x: np.ndarray) -> np.ndarray:
    return pd.Series(x).rank(pct=True).to_numpy()


class RankAverageEnsemble:
    """Averages the percentile ranks of several models' probabilities."""

    def __init__(self, models):
        self.models = models

    def fit(self, X, y):
        self.models = [clone(m).fit(X, y) for m in self.models]
        return self

    def predict_proba(self, X):
        p = np.mean([_rank01(m.predict_proba(X)[:, 1]) for m in self.models], axis=0)
        return np.column_stack([1 - p, p])

    def get_params(self, deep=False):
        return {"models": self.models}

    def set_params(self, **params):
        self.__dict__.update(params)
        return self
