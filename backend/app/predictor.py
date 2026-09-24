"""Load the trained model file once and use it for predictions.

The file written by `scripts/train_model.py` holds more than the scikit-learn
pipeline: it also records the feature list, class order, Elo settings and form
window the model was trained with. Serving reads those settings from the file
instead of the current code defaults, so changing a default in `features.py`
cannot silently feed an old model different features.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Protocol

import joblib
import numpy as np
import pandas as pd

from app.features import ALL_FEATURE_COLUMNS, EloConfig, build_features, build_match_features
from app.match_model import OUTCOMES

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parents[1] / "models"
DEFAULT_MODEL_VERSION = "v2"


class ProbabilisticModel(Protocol):
    """The one method serving needs from a fitted scikit-learn classifier."""

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray: ...


class ModelLoadError(RuntimeError):
    """The model file exists but cannot be used by this version of the code."""


def model_path() -> Path:
    """Where to load the model from: $MODEL_PATH, else the $MODEL_VERSION (default v2) file."""
    if explicit := os.environ.get("MODEL_PATH"):
        return Path(explicit)
    version = os.environ.get("MODEL_VERSION", DEFAULT_MODEL_VERSION)
    return MODELS_DIR / f"match_outcome_logreg_{version}.joblib"


@dataclass(frozen=True)
class Predictor:
    """A trained model plus the settings needed to build its inputs."""

    model: ProbabilisticModel
    version: str
    trained_at: str
    feature_columns: list[str]
    elo_config: EloConfig
    form_window: int
    train_seasons: list[str]
    validation_season: str
    test_season: str
    metrics: dict[str, dict[str, dict[str, float]]]

    @classmethod
    def from_bundle(cls, bundle: dict[str, Any]) -> "Predictor":
        """Build from the dict `scripts/train_model.py` saves.

        Raises:
            ModelLoadError: If the file needs features this code does not
                build, or has different classes.
        """
        # Each version trains on its own subset (v1 per-team, v2 differences);
        # build_features produces all of them, so any subset can be served.
        unknown = [c for c in bundle["feature_columns"] if c not in ALL_FEATURE_COLUMNS]
        if unknown:
            raise ModelLoadError(
                f"model expects features {unknown} that this code does not build; retrain the model"
            )
        if bundle["classes"] != OUTCOMES:
            raise ModelLoadError(f"model classes {bundle['classes']} != {OUTCOMES}")
        return cls(
            model=bundle["model"],
            version=bundle["version"],
            trained_at=bundle["trained_at"],
            feature_columns=bundle["feature_columns"],
            elo_config=bundle["elo_config"],
            form_window=bundle["form_window"],
            train_seasons=bundle["train_seasons"],
            validation_season=bundle["validation_season"],
            test_season=bundle["test_season"],
            metrics=bundle["metrics"],
        )

    def match_features(
        self, history: pd.DataFrame, home_team_id: int, away_team_id: int, as_of: date
    ) -> pd.Series:
        """Features for a hypothetical match, built with this model's settings."""
        return build_match_features(
            history, home_team_id, away_team_id, as_of, self.elo_config, self.form_window
        )

    def history_features(self, matches: pd.DataFrame) -> pd.DataFrame:
        """Pre-match features for every real match, built with this model's settings."""
        return build_features(matches, self.elo_config, self.form_window)

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """Outcome probabilities, shape (n, 3), columns in OUTCOMES order (A, D, H)."""
        return self.model.predict_proba(features[self.feature_columns])

    def split_of(self, season: str) -> str:
        """Which part of training a season was used for, or "unseen"."""
        if season in self.train_seasons:
            return "train"
        if season == self.validation_season:
            return "validation"
        if season == self.test_season:
            return "test"
        return "unseen"


def load_predictor(path: Path) -> Predictor | None:
    """Load the model file, or return None if there is no file yet.

    Only load files you produced yourself: joblib files are pickles and can run
    code when loaded.

    Raises:
        ModelLoadError: If the file exists but is incompatible.
    """
    if not path.exists():
        log.warning("no model file at %s; prediction endpoints will return 503", path)
        return None
    predictor = Predictor.from_bundle(joblib.load(path))
    log.info("loaded model %s (trained %s) from %s", predictor.version, predictor.trained_at, path)
    return predictor
