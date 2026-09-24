"""Tests for the training script's data handling (no database, no fitting)."""

import pandas as pd

from app.features import build_features
from scripts.train_model import TEST_SEASON, TRAIN_SEASONS, VALIDATION_SEASON, splits
from test_features import fixture, frame


def test_unplayed_fixtures_are_left_out_of_every_split() -> None:
    """Fixtures from football-data.org sit in the same table with NULL goals.
    They have no result to learn from, so no split may contain them."""
    first, last = TRAIN_SEASONS[0], TRAIN_SEASONS[-1]
    rows = []
    for season in (first, last, VALIDATION_SEASON, TEST_SEASON):
        year = int(season[:4])
        rows += [
            fixture(season, pd.Timestamp(year, 8, 10).date(), 1, 2, 2, 1),
            fixture(season, pd.Timestamp(year, 8, 17).date(), 2, 1, None, None),
        ]
    features = build_features(frame(rows))
    assert features["result"].isna().sum() == 4  # unplayed fixtures get no result

    train, valid, test = splits(features)
    assert (len(train), len(valid), len(test)) == (2, 1, 1)
    for split in (train, valid, test):
        assert split["result"].notna().all()
        assert set(split["result"]) == {"H"}
