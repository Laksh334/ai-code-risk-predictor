"""B1-B4 - NLP signals, packaged model, explanations, forecast."""

import numpy as np
import pandas as pd
import pytest

from ml.forecast import project
from ml.nlp import lexicon_features
from ml.package import RISK_THRESHOLDS
from ml.predictor import RiskPredictor, predict
from pipeline.scanner import scan_repository


@pytest.fixture(scope="module")
def predictor():
    return RiskPredictor.load()


@pytest.fixture(scope="module")
def features(repo):
    return scan_repository(str(repo["path"])).features


def test_message_lexicon():
    f = lexicon_features(pd.Series(["fixed this stupid bug again", "WIP", "Add proxy support",
                                    'Revert "x"\n\nThis reverts commit abc1234.']))
    assert f["msg_frustrated"].tolist() == [1, 0, 0, 0]
    assert f["msg_rushed"].tolist() == [0, 1, 0, 0]
    assert f["msg_revert"].tolist() == [0, 0, 0, 1]


def test_backend_uses_same_risk_levels():
    from app.services.risk import THRESHOLDS

    assert {level.value: t for t, level in THRESHOLDS} == RISK_THRESHOLDS


def test_levels_follow_thresholds(predictor):
    assert predictor.risk_level(0.50) == "critical"
    assert predictor.risk_level(0.25) == "high"
    assert predictor.risk_level(0.12) == "medium"
    assert predictor.risk_level(0.02) == "low"


def test_predict_single_file_with_missing_features():
    small = predict({"loc": 50, "commit_count": 3}, explain=False)
    big = predict({"loc": 3000, "commit_count": 800, "bug_fix_count": 150}, explain=False)
    assert 0 <= small["risk_score"] < big["risk_score"] <= 1
    assert big["risk_level"] in {"medium", "high", "critical"}


def test_empty_input_is_not_an_error(predictor, features):
    empty = features.iloc[0:0]
    assert predictor.predict(empty).empty and predictor.predict(empty, explain=False).empty
    assert len(predictor.risk_scores(empty)) == 0


def test_full_prediction_and_exact_shap(predictor, features):
    res = predictor.predict(features)
    assert list(res["priority_rank"]) == list(range(1, len(res) + 1))
    assert res["risk_score"].is_monotonic_decreasing
    top = res.iloc[0]
    assert top["explanation"] and top["factors"] and top["recommendation"]
    # calibrated SHAP: a*base + b + sum(impacts) == log-odds of the risk score
    X = predictor._prepare(features)
    p = predictor.risk_scores(features)
    sv = predictor.explainer.shap_values(X) * predictor.a
    total = predictor.a * predictor.explainer.base_value + predictor.b + sv.sum(axis=1)
    assert np.allclose(total, np.log(p / (1 - p)), atol=1e-8)


def test_low_risk_files_get_no_action_advice(predictor, features):
    res = predictor.predict(features)
    low = res[res["risk_level"] == "low"]
    assert (low["recommendation"] == "Low risk: no action needed right now.").all()


def test_debt_projection():
    hist = pd.DataFrame({"date": pd.date_range("2022-01-01", periods=6, freq="6MS", tz="UTC"),
                         "expected_bug_prone_files": [1, 2, 3, 4, 5, 6.0],
                         "risk_weighted_kloc": [5, 5, 5, 5, 5, 5.0]})
    proj, trend = project(hist)
    assert len(proj) == 3 and (proj["date"] > hist["date"].max()).all()
    assert trend["expected_bug_prone_files"]["direction"] == "rising"
    assert trend["risk_weighted_kloc"]["direction"] == "flat"
    assert (proj["expected_bug_prone_files_low"] <= proj["expected_bug_prone_files"]).all()
