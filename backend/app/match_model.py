"""The baseline match outcome model, the comparison baselines, and scoring.

Probabilities everywhere are arrays of shape (n_matches, 3) with columns in
OUTCOMES order: away win, draw, home win. That is the order scikit-learn sorts
the string labels into, so model output and baselines line up column for column.
"""

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

OUTCOMES = ["A", "D", "H"]


def make_pipeline(c: float = 1.0) -> Pipeline:
    """Multinomial logistic regression with imputation and scaling.

    The imputer fills a missing feature (e.g. form for a team's first match in the
    data) with its training-set mean. It learns that mean from the training rows
    only, like the scaler, so no statistics from later seasons leak in.

    Args:
        c: Inverse L2 regularisation strength. Smaller = simpler model.
    """
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="mean")),
            ("scale", StandardScaler()),
            # With 3 classes and the default lbfgs solver this is a multinomial (softmax) model.
            ("logreg", LogisticRegression(C=c, max_iter=1000)),
        ]
    )


def one_hot(results: pd.Series) -> np.ndarray:
    """"H"/"D"/"A" labels -> 0/1 matrix in OUTCOMES order."""
    unknown = set(results) - set(OUTCOMES)
    if unknown:
        raise ValueError(f"unexpected results: {sorted(map(str, unknown))}")
    return (results.to_numpy()[:, None] == np.array(OUTCOMES)[None, :]).astype(float)


def always_home_proba(n: int) -> np.ndarray:
    """The naive "home team always wins" pick, as certain probabilities."""
    return np.tile([0.0, 0.0, 1.0], (n, 1))


def base_rate_proba(train_results: pd.Series, n: int) -> np.ndarray:
    """Predict the training-set frequency of each outcome for every match."""
    rates = one_hot(train_results).mean(axis=0)
    return np.tile(rates, (n, 1))


def implied_proba(odds: pd.DataFrame) -> np.ndarray:
    """Bookmaker decimal odds -> probabilities with the bookmaker's margin removed.

    1/odds gives each outcome's implied probability, but these add up to a bit
    more than 1 (the "overround", the bookmaker's cut). Dividing by the sum
    rescales them to add up to exactly 1.

    Args:
        odds: Columns odds_away, odds_draw, odds_home (any column order).
    """
    raw = 1.0 / odds[["odds_away", "odds_draw", "odds_home"]].to_numpy(dtype=float)
    return raw / raw.sum(axis=1, keepdims=True)


def brier_score(y_true: pd.Series, proba: np.ndarray) -> float:
    """Multi-class Brier score: mean squared distance from the true one-hot outcome.

    0 is perfect. Always saying 1/3 for everything scores 0.667. A confident
    wrong pick scores 2.
    """
    return float(np.mean(np.sum((proba - one_hot(y_true)) ** 2, axis=1)))


def score(y_true: pd.Series, proba: np.ndarray) -> dict[str, float]:
    """Accuracy, log loss and Brier score for one set of predictions."""
    predicted = np.array(OUTCOMES)[proba.argmax(axis=1)]
    return {
        "accuracy": float(accuracy_score(y_true, predicted)),
        # Certain-but-wrong predictions (probability 0 on what happened) are clipped
        # to a tiny probability by scikit-learn, giving a very large but finite loss.
        "log_loss": float(log_loss(one_hot(y_true), np.clip(proba, 0.0, 1.0))),
        "brier": brier_score(y_true, proba),
    }
