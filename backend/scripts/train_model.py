"""Train a match outcome model and compare it with the baselines.

Run inside the backend container (after scripts.load_history):

    docker compose exec backend python -m scripts.train_model              # v2
    docker compose exec backend python -m scripts.train_model --features v1

Seasons are split by time, never shuffled:

    train       2015-16 .. 2023-24   fit the model
    validation  2024-25              every choice: settings, features, C
    test        2025-26              scored once, for the final model only

Feature sets:

    v1  Per-team Elo and form (home_elo, away_elo, home_form_points, ...).
        Default Elo settings; only C is tuned.
    v2  Home-minus-away differences (elo_diff, form_*_diff). Tunes the Elo
        K-factor, the pull towards the average between seasons, the promoted
        teams' starting rating, whether to keep form points, and C.

The test season is used after every choice is final: the chosen model is scored
on it next to the v1 model (if its file exists) and the baselines, and nothing
is changed afterwards. The model (fit on the training seasons only) is saved
with joblib to backend/models/match_outcome_logreg_<version>.joblib, together
with the feature list, class order, Elo settings and all metrics.
"""

import argparse
import asyncio
import itertools
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import Pipeline

from app.db import engine
from app.features import (
    DIFF_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    FORM_WINDOW,
    EloConfig,
    add_difference_features,
    build_features,
    elo_ratings,
)
from app.football_data import ODDS_COLUMNS
from app.match_model import (
    MODEL_LABEL,
    OUTCOMES,
    always_home_proba,
    base_rate_proba,
    implied_proba,
    make_pipeline,
    score,
)
from app.predictor import MODELS_DIR, ModelLoadError, load_predictor
from app.repository import load_matches as read_matches

log = logging.getLogger("train_model")

TRAIN_SEASONS = [f"20{y:02d}-{y + 1:02d}" for y in range(15, 24)]  # 2015-16 .. 2023-24
VALIDATION_SEASON = "2024-25"
TEST_SEASON = "2025-26"
C_GRID = [0.001, 0.01, 0.1, 1.0, 10.0]

# v2 search space. Every combination is scored on the validation season only.
K_GRID = [10.0, 15.0, 20.0, 25.0, 30.0, 40.0]
REGRESSION_GRID = [0.0, 0.1, 0.2, 0.3, 0.4]
PROMOTED_OFFSET_GRID = [-150.0, -100.0, -50.0, 0.0, 50.0]
V2_COLUMNS_WITH_POINTS = DIFF_FEATURE_COLUMNS
V2_COLUMNS = [c for c in DIFF_FEATURE_COLUMNS if c != "form_points_diff"]


@dataclass(frozen=True)
class Candidate:
    """One point in the search, scored on the validation season."""

    elo: EloConfig
    columns: list[str]
    c: float
    log_loss: float


async def load_matches() -> pd.DataFrame:
    """Every match in the database, loaded the same way the API loads it."""
    try:
        async with engine.connect() as conn:
            return await read_matches(conn)
    finally:
        await engine.dispose()


def fit(train: pd.DataFrame, columns: list[str], c: float) -> Pipeline:
    model = make_pipeline(c)
    model.fit(train[columns], train["result"].astype(str))
    if list(model.classes_) != OUTCOMES:
        raise RuntimeError(f"unexpected class order {model.classes_}")
    return model


def splits(features: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Played matches in the train, validation and test seasons."""
    played = features["result"].notna()
    return (
        features[played & features["season"].isin(TRAIN_SEASONS)],
        features[played & (features["season"] == VALIDATION_SEASON)],
        features[played & (features["season"] == TEST_SEASON)],
    )


def elo_grid(feature_set: str) -> list[EloConfig]:
    if feature_set == "v1":
        return [EloConfig()]
    return [
        EloConfig(k=k, season_regression=r, promoted_offset=p)
        for k, r, p in itertools.product(K_GRID, REGRESSION_GRID, PROMOTED_OFFSET_GRID)
    ]


def column_sets(feature_set: str) -> list[list[str]]:
    if feature_set == "v1":
        return [FEATURE_COLUMNS]
    return [V2_COLUMNS, V2_COLUMNS_WITH_POINTS]


def search(matches: pd.DataFrame, feature_set: str) -> list[Candidate]:
    """Score every Elo setting x column set x C on the validation season.

    Form does not depend on the Elo settings, so it is built once and only the
    Elo columns (and their differences) are recomputed per setting. The test
    season is never looked at here.

    Returns:
        Candidates sorted best (lowest validation log loss) first.
    """
    base = build_features(matches, EloConfig(), FORM_WINDOW)
    elo_configs = elo_grid(feature_set)
    candidates = []
    for n, elo in enumerate(elo_configs, 1):
        features = base.copy()
        features[["home_elo", "away_elo"]] = elo_ratings(matches, elo)
        features = add_difference_features(features)
        train, valid, _ = splits(features)
        for columns, c in itertools.product(column_sets(feature_set), C_GRID):
            proba = fit(train, columns, c).predict_proba(valid[columns])
            loss = score(valid["result"], proba)["log_loss"]
            candidates.append(Candidate(elo, columns, c, loss))
        if n % 25 == 0 or n == len(elo_configs):
            log.info("searched %d/%d Elo settings", n, len(elo_configs))
    return sorted(candidates, key=lambda cand: cand.log_loss)


def describe(cand: Candidate) -> str:
    points = "with" if "form_points_diff" in cand.columns else "without"
    if cand.columns == FEATURE_COLUMNS:
        points = "per-team"
    return (
        f"K={cand.elo.k:<4g} regression={cand.elo.season_regression:<4g} "
        f"promoted={cand.elo.promoted_offset:+5g}  {points:<8} points  C={cand.c:<6g} "
        f"validation log loss {cand.log_loss:.4f}"
    )


def evaluate(
    proba: np.ndarray, train: pd.DataFrame, split: pd.DataFrame, odds: pd.DataFrame
) -> dict[str, dict[str, float]]:
    """Score the model's probabilities and every baseline on one split."""
    y = split["result"]
    results = {
        MODEL_LABEL: score(y, proba),
        "always home win": score(y, always_home_proba(len(split))),
        "training base rates": score(y, base_rate_proba(train["result"], len(split))),
    }
    has_odds = odds.loc[split.index].notna().all(axis=1)
    if has_odds.all():
        results["bookmaker (Bet365)"] = score(y, implied_proba(odds.loc[split.index]))
    else:
        log.warning("%d matches lack odds; bookmaker baseline skipped", (~has_odds).sum())
    return results


def previous_model_proba(
    matches: pd.DataFrame, version: str, split: pd.DataFrame
) -> np.ndarray | None:
    """Another saved model's probabilities for `split`, built with its own settings."""
    try:
        predictor = load_predictor(MODELS_DIR / f"match_outcome_logreg_{version}.joblib")
    except ModelLoadError as exc:
        log.warning("cannot compare with %s: %s", version, exc)
        return None
    if predictor is None:
        return None
    features = predictor.history_features(matches)
    return predictor.predict_proba(features.loc[split.index])


def print_table(title: str, results: dict[str, dict[str, float]], n: int) -> None:
    print(f"\n{title} ({n} matches)")
    print(f"{'':<24}{'accuracy':>10}{'log loss':>10}{'brier':>8}")
    for name, m in results.items():
        print(f"{name:<24}{m['accuracy']:>10.3f}{m['log_loss']:>10.4f}{m['brier']:>8.4f}")


def main(version: str, feature_set: str, force: bool) -> None:
    out_path = MODELS_DIR / f"match_outcome_logreg_{version}.joblib"
    if out_path.exists() and not force:
        raise SystemExit(f"{out_path.name} already exists; pick another --version or pass --force")

    matches = asyncio.run(load_matches())
    odds = matches[ODDS_COLUMNS]

    # --- 1. Every choice, made on the validation season --------------------------------
    candidates = search(matches, feature_set)
    best = candidates[0]
    print(f"\nTop validation results ({len(candidates)} tried, {VALIDATION_SEASON}):")
    for cand in candidates[:10]:
        print("  " + describe(cand))
    if feature_set == "v2":
        for label, with_points in (("with", True), ("without", False)):
            top = next(c for c in candidates if ("form_points_diff" in c.columns) == with_points)
            print(f"best {label} form points: {top.log_loss:.4f}")
    print("chosen: " + describe(best))

    # Features are built over the whole history at once: each row only ever looks
    # backwards in time, so later seasons cannot affect earlier rows.
    features = build_features(matches, best.elo, FORM_WINDOW)
    train, valid, test = splits(features)
    for name, split in (("train", train), ("validation", valid), ("test", test)):
        if split.empty:
            raise SystemExit(f"no played matches in the {name} split; run scripts.load_history")
        log.info(
            "%-10s %s .. %s, %d matches",
            name,
            split["match_date"].min(),
            split["match_date"].max(),
            len(split),
        )
    model = fit(train, best.columns, best.c)

    # --- 2. The test season, once, for the final choice only ---------------------------
    metrics = {
        "validation": evaluate(model.predict_proba(valid[best.columns]), train, valid, odds),
        "test": evaluate(model.predict_proba(test[best.columns]), train, test, odds),
    }
    print_table(f"Validation {VALIDATION_SEASON}", metrics["validation"], len(valid))

    comparison = {f"{version} (this model)": metrics["test"][MODEL_LABEL]}
    if version != "v1" and (v1_proba := previous_model_proba(matches, "v1", test)) is not None:
        comparison = {"v1": score(test["result"], v1_proba), **comparison}
    comparison.update({k: v for k, v in metrics["test"].items() if k != MODEL_LABEL})
    print_table(f"Test {TEST_SEASON}", comparison, len(test))

    coefs = pd.DataFrame(model.named_steps["logreg"].coef_, index=OUTCOMES, columns=best.columns)
    print("\nCoefficients (standardised features; + means more likely):")
    print(coefs.T.round(3).to_string())
    print(
        "Intercepts:",
        dict(zip(OUTCOMES, model.named_steps["logreg"].intercept_.round(3), strict=True)),
    )

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "version": version,
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": model,
            "feature_columns": best.columns,
            "classes": OUTCOMES,
            "elo_config": best.elo,
            "form_window": FORM_WINDOW,
            "c": best.c,
            "train_seasons": TRAIN_SEASONS,
            "validation_season": VALIDATION_SEASON,
            "test_season": TEST_SEASON,
            "metrics": metrics,
            "search": [
                {**asdict(c.elo), "columns": c.columns, "c": c.c, "log_loss": c.log_loss}
                for c in candidates
            ],
            "sklearn_version": sklearn.__version__,
            "numpy_version": np.__version__,
        },
        out_path,
    )
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the match outcome model.")
    parser.add_argument(
        "--features", choices=["v1", "v2"], default="v2", help="feature set and search (default v2)"
    )
    parser.add_argument("--version", help="version name in the file name (default: --features)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing model file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main(args.version or args.features, args.features, args.force)
