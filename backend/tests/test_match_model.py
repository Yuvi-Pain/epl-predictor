"""Tests for the model pipeline, baselines and scoring helpers."""

import numpy as np
import pandas as pd
import pytest

from app.features import FEATURE_COLUMNS
from app.match_model import (
    OUTCOMES,
    always_home_proba,
    base_rate_proba,
    brier_score,
    implied_proba,
    make_pipeline,
    one_hot,
    score,
)


def test_one_hot_uses_outcome_order() -> None:
    assert OUTCOMES == ["A", "D", "H"]
    np.testing.assert_array_equal(
        one_hot(pd.Series(["H", "A", "D"])), [[0, 0, 1], [1, 0, 0], [0, 1, 0]]
    )


def test_one_hot_rejects_unknown_labels() -> None:
    with pytest.raises(ValueError, match="unexpected"):
        one_hot(pd.Series(["H", "X"]))


def test_implied_proba_removes_the_margin() -> None:
    odds = pd.DataFrame({"odds_home": [2.0, 1.5], "odds_draw": [3.4, 4.0], "odds_away": [3.8, 6.5]})
    proba = implied_proba(odds)
    np.testing.assert_allclose(proba.sum(axis=1), 1.0)
    raw = np.array([1 / 3.8, 1 / 3.4, 1 / 2.0])
    np.testing.assert_allclose(proba[0], raw / raw.sum())  # columns in A, D, H order


def test_brier_score_reference_values() -> None:
    y = pd.Series(["H", "D"])
    assert brier_score(y, one_hot(y)) == 0.0
    assert brier_score(y, np.full((2, 3), 1 / 3)) == pytest.approx(2 / 3)
    assert brier_score(pd.Series(["A"]), always_home_proba(1)) == pytest.approx(2.0)


def test_score_on_perfect_and_uniform_predictions() -> None:
    y = pd.Series(["H", "D", "A", "H"])
    perfect = score(y, one_hot(y))
    assert perfect["accuracy"] == 1.0 and perfect["log_loss"] == pytest.approx(0.0, abs=1e-9)
    uniform = score(y, np.full((4, 3), 1 / 3))
    assert uniform["log_loss"] == pytest.approx(np.log(3))


def test_always_home_scores_like_the_home_win_rate() -> None:
    y = pd.Series(["H", "H", "D", "A"])
    assert score(y, always_home_proba(4))["accuracy"] == 0.5


def test_base_rates_come_from_training_results() -> None:
    np.testing.assert_allclose(
        base_rate_proba(pd.Series(["H", "H", "D", "A"]), 2), [[0.25, 0.25, 0.5]] * 2
    )


def test_pipeline_classes_and_probabilities() -> None:
    rng = np.random.default_rng(0)
    X = pd.DataFrame(rng.normal(size=(60, len(FEATURE_COLUMNS))), columns=FEATURE_COLUMNS)
    X.iloc[0, 3] = np.nan  # missing form is imputed, not an error
    y = pd.Series(np.tile(["H", "D", "A"], 20))
    model = make_pipeline().fit(X, y)
    assert list(model.classes_) == OUTCOMES
    np.testing.assert_allclose(model.predict_proba(X).sum(axis=1), 1.0)
