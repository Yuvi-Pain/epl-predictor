"""Symmetry checks for the v2 model, which trains on home-minus-away differences.

v1 took home and away Elo as separate features with separately learned weights,
so two equal teams got a different home advantage at different rating levels.
These tests pin down what v2 guarantees instead:

* Equal teams get the same prediction whatever their rating level.
* Swapping home and away negates every feature, and the home advantage (the
  log-odds of a home win over an away win for two equal teams) is the same
  amount for every pairing.

They run against a pipeline fitted on synthetic data, and also against the
saved v2 model file when it exists (it is git-ignored, so CI may skip that).
"""

from typing import Any

import joblib
import numpy as np
import pandas as pd
import pytest

from app.features import DIFF_FEATURE_COLUMNS, FEATURE_COLUMNS, FORM_STATS, add_difference_features
from app.match_model import OUTCOMES, make_pipeline
from app.predictor import MODELS_DIR, Predictor
from fakes import make_bundle

A, D, H = (OUTCOMES.index(o) for o in ("A", "D", "H"))
V2_FILE = MODELS_DIR / "match_outcome_logreg_v2.joblib"


def synthetic_v2_predictor() -> Predictor:
    """A v2-style model fitted on made-up matches where the stronger side, and the home side, win more."""
    rng = np.random.default_rng(0)
    n = 3000
    X = pd.DataFrame(rng.normal(size=(n, len(DIFF_FEATURE_COLUMNS))), columns=DIFF_FEATURE_COLUMNS)
    X["elo_diff"] *= 150
    strength = 0.3 + X["elo_diff"] / 200 + 0.2 * X["form_goals_for_diff"]
    logits = np.column_stack([-strength, np.full(n, -0.2), strength])
    proba = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    y = pd.Series([OUTCOMES[rng.choice(3, p=p)] for p in proba])
    model = make_pipeline(1.0).fit(X, y)
    return Predictor.from_bundle({**make_bundle(model), "feature_columns": DIFF_FEATURE_COLUMNS})


def saved_v2_predictor() -> Predictor:
    bundle: dict[str, Any] = joblib.load(V2_FILE)
    return Predictor.from_bundle(bundle)


PREDICTORS = [
    pytest.param(synthetic_v2_predictor, id="synthetic"),
    pytest.param(
        saved_v2_predictor,
        id="saved-v2",
        marks=pytest.mark.skipif(not V2_FILE.exists(), reason=f"no {V2_FILE.name}; train it first"),
    ),
]


def team(elo: float, *form: float) -> dict[str, float]:
    """One side's per-team features: Elo, then the form stats in FORM_STATS order."""
    return {"elo": elo, **dict(zip(FORM_STATS, form, strict=True))}


def fixture_rows(pairs: list[tuple[dict[str, float], dict[str, float]]]) -> pd.DataFrame:
    """Per-team features for (home, away) pairs, plus the differences, as build_features gives them."""
    rows = []
    for home, away in pairs:
        row = {"home_elo": home["elo"], "away_elo": away["elo"]}
        for stat in FORM_STATS:
            row[f"home_form_{stat}"] = home[stat]
            row[f"away_form_{stat}"] = away[stat]
        rows.append(row)
    return add_difference_features(pd.DataFrame(rows, columns=FEATURE_COLUMNS))


STRONG = team(1780, 2.4, 2.2, 0.8, 6.1, 3.0)
AVERAGE = team(1520, 1.4, 1.3, 1.3, 4.2, 4.3)
WEAK = team(1330, 0.6, 0.8, 2.1, 3.0, 5.9)


@pytest.mark.parametrize("make_predictor", PREDICTORS)
def test_equal_teams_get_the_same_prediction_at_any_rating_level(make_predictor: Any) -> None:
    predictor = make_predictor()
    form = {"points": 1.5, "goals_for": 1.4, "goals_against": 1.2, "sot_for": 4.5, "sot_against": 4.0}
    levels = [1250, 1400, 1500, 1650, 1850]
    pairs = [({"elo": r, **form}, {"elo": r, **form}) for r in levels]
    proba = predictor.predict_proba(fixture_rows(pairs))

    np.testing.assert_allclose(proba, np.tile(proba[0], (len(levels), 1)), atol=1e-12)
    assert proba[0, H] > proba[0, A], "equal teams: home side should be favoured"


@pytest.mark.parametrize("make_predictor", PREDICTORS)
def test_equal_gaps_get_the_same_prediction_at_any_rating_level(make_predictor: Any) -> None:
    predictor = make_predictor()
    pairs = [
        (team(base + 120, 1.5, 1.4, 1.2, 4.5, 4.0), team(base, 1.5, 1.4, 1.2, 4.5, 4.0))
        for base in (1300, 1500, 1700)
    ]
    proba = predictor.predict_proba(fixture_rows(pairs))
    np.testing.assert_allclose(proba, np.tile(proba[0], (3, 1)), atol=1e-12)


def test_swapping_home_and_away_negates_every_difference() -> None:
    features = fixture_rows([(STRONG, WEAK), (WEAK, STRONG)])
    np.testing.assert_allclose(
        features.loc[0, DIFF_FEATURE_COLUMNS].to_numpy(dtype=float),
        -features.loc[1, DIFF_FEATURE_COLUMNS].to_numpy(dtype=float),
    )


@pytest.mark.parametrize("make_predictor", PREDICTORS)
def test_swapping_home_and_away_is_consistent(make_predictor: Any) -> None:
    """For X v Y and Y v X, log(P(home win) / P(away win)) adds up to twice the
    home advantage, and that total is the same for every pair of teams."""
    predictor = make_predictor()
    pairs = [(STRONG, WEAK), (STRONG, AVERAGE), (AVERAGE, WEAK), (AVERAGE, AVERAGE)]
    forward = predictor.predict_proba(fixture_rows(pairs))
    swapped = predictor.predict_proba(fixture_rows([(away, home) for home, away in pairs]))

    home_edge = np.log(forward[:, H] / forward[:, A]) + np.log(swapped[:, H] / swapped[:, A])
    np.testing.assert_allclose(home_edge, home_edge[0], atol=1e-9)
    assert home_edge[0] > 0, "playing at home should help"

    # Each team's chance of winning is higher at home than away...
    np.testing.assert_array_less(swapped[:, A], forward[:, H])
    np.testing.assert_array_less(forward[:, A], swapped[:, H])
    # ...and the stronger side is favoured either way round.
    assert forward[0, H] > forward[0, A] and swapped[0, A] > swapped[0, H]


def test_v2_uses_no_per_team_levels() -> None:
    """The guarantee above only holds while v2 sees differences alone."""
    predictor = synthetic_v2_predictor()
    assert set(predictor.feature_columns) <= set(DIFF_FEATURE_COLUMNS)
    if V2_FILE.exists():
        assert set(saved_v2_predictor().feature_columns) <= set(DIFF_FEATURE_COLUMNS)
