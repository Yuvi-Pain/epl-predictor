"""Train the baseline match outcome model and compare it with simple baselines.

Run inside the backend container (after scripts.load_history):

    docker compose exec backend python -m scripts.train_model
    docker compose exec backend python -m scripts.train_model --version v2 --force

Seasons are split by time, never shuffled:

    train       2015-16 .. 2023-24   fit the model
    validation  2024-25              pick the regularisation strength C
    test        2025-26              scored once at the end

The chosen model (fit on the training seasons only) is saved with joblib to
backend/models/match_outcome_logreg_<version>.joblib, together with the feature
list, class order, Elo settings and all metrics.
"""

import argparse
import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.pipeline import Pipeline
from sqlalchemy import select

from app.db import engine
from app.features import FEATURE_COLUMNS, FORM_WINDOW, EloConfig, build_features
from app.football_data import ODDS_COLUMNS
from app.match_model import (
    OUTCOMES,
    always_home_proba,
    base_rate_proba,
    implied_proba,
    make_pipeline,
    score,
)
from app.models import Match

log = logging.getLogger("train_model")

TRAIN_SEASONS = [f"20{y:02d}-{y + 1:02d}" for y in range(15, 24)]  # 2015-16 .. 2023-24
VALIDATION_SEASON = "2024-25"
TEST_SEASON = "2025-26"
C_GRID = [0.001, 0.01, 0.1, 1.0, 10.0]
MODELS_DIR = Path(__file__).resolve().parents[1] / "models"


async def load_matches() -> pd.DataFrame:
    """Every match in the database as a DataFrame, one row per fixture."""
    columns = [c for c in Match.__table__.columns if c.name != "id"]
    async with engine.connect() as conn:
        rows = (await conn.execute(select(*columns).order_by(Match.match_date, Match.id))).all()
    await engine.dispose()
    df = pd.DataFrame(rows, columns=[c.name for c in columns])
    for col in ("home_goals", "away_goals", "home_shots_on_target", "away_shots_on_target"):
        df[col] = df[col].astype("Int16")
    return df


def fit(train: pd.DataFrame, c: float) -> Pipeline:
    model = make_pipeline(c)
    model.fit(train[FEATURE_COLUMNS], train["result"].astype(str))
    if list(model.classes_) != OUTCOMES:
        raise RuntimeError(f"unexpected class order {model.classes_}")
    return model


def choose_c(train: pd.DataFrame, valid: pd.DataFrame) -> float:
    """The C from C_GRID with the lowest validation log loss."""
    losses = {}
    for c in C_GRID:
        proba = fit(train, c).predict_proba(valid[FEATURE_COLUMNS])
        losses[c] = score(valid["result"], proba)["log_loss"]
        log.info("C=%-6g validation log loss %.4f", c, losses[c])
    return min(losses, key=losses.__getitem__)


def evaluate(
    model: Pipeline, train: pd.DataFrame, split: pd.DataFrame, odds: pd.DataFrame
) -> dict[str, dict[str, float]]:
    """Score the model and every baseline on one split."""
    y = split["result"]
    results = {
        "logistic regression": score(y, model.predict_proba(split[FEATURE_COLUMNS])),
        "always home win": score(y, always_home_proba(len(split))),
        "training base rates": score(y, base_rate_proba(train["result"], len(split))),
    }
    has_odds = odds.loc[split.index].notna().all(axis=1)
    if has_odds.all():
        results["bookmaker (Bet365)"] = score(y, implied_proba(odds.loc[split.index]))
    else:
        log.warning("%d matches lack odds; bookmaker baseline skipped", (~has_odds).sum())
    return results


def print_table(title: str, results: dict[str, dict[str, float]], n: int) -> None:
    print(f"\n{title} ({n} matches)")
    print(f"{'':<22}{'accuracy':>10}{'log loss':>10}{'brier':>8}")
    for name, m in results.items():
        print(f"{name:<22}{m['accuracy']:>10.3f}{m['log_loss']:>10.4f}{m['brier']:>8.4f}")


def main(version: str, force: bool) -> None:
    out_path = MODELS_DIR / f"match_outcome_logreg_{version}.joblib"
    if out_path.exists() and not force:
        raise SystemExit(f"{out_path.name} already exists; pick another --version or pass --force")

    matches = asyncio.run(load_matches())
    elo_config = EloConfig()
    # Features are built over the whole history at once: each row only ever looks
    # backwards in time, so later seasons cannot affect earlier rows.
    features = build_features(matches, elo_config)
    odds = matches[ODDS_COLUMNS]

    played = features["result"].notna()
    train = features[played & features["season"].isin(TRAIN_SEASONS)]
    valid = features[played & (features["season"] == VALIDATION_SEASON)]
    test = features[played & (features["season"] == TEST_SEASON)]
    for name, split in (("train", train), ("validation", valid), ("test", test)):
        if split.empty:
            raise SystemExit(f"no played matches in the {name} split; run scripts.load_history")
        log.info("%-10s %s .. %s, %d matches", name, split["match_date"].min(),
                 split["match_date"].max(), len(split))

    best_c = choose_c(train, valid)
    log.info("chosen C=%g", best_c)
    model = fit(train, best_c)

    metrics = {
        "validation": evaluate(model, train, valid, odds),
        "test": evaluate(model, train, test, odds),
    }
    print_table(f"Validation {VALIDATION_SEASON}", metrics["validation"], len(valid))
    print_table(f"Test {TEST_SEASON}", metrics["test"], len(test))

    coefs = pd.DataFrame(model.named_steps["logreg"].coef_, index=OUTCOMES, columns=FEATURE_COLUMNS)
    print("\nCoefficients (standardised features; + means more likely):")
    print(coefs.T.round(3).to_string())

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {
            "version": version,
            "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "model": model,
            "feature_columns": FEATURE_COLUMNS,
            "classes": OUTCOMES,
            "elo_config": elo_config,
            "form_window": FORM_WINDOW,
            "c": best_c,
            "train_seasons": TRAIN_SEASONS,
            "validation_season": VALIDATION_SEASON,
            "test_season": TEST_SEASON,
            "metrics": metrics,
            "sklearn_version": sklearn.__version__,
            "numpy_version": np.__version__,
        },
        out_path,
    )
    print(f"\nSaved {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train the baseline match outcome model.")
    parser.add_argument("--version", default="v1", help="version name in the file name (default v1)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing model file")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main(args.version, args.force)
