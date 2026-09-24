"""Tests for pre-match features. Pure pandas on synthetic fixtures; no database.

The key test is `test_no_feature_uses_the_match_itself_or_later`: for every date
in a synthetic three-season league, it rewrites (or blanks) the results of every
match on or after that date and checks that the features of the matches on that
date do not move. If any feature read the match's own result, a same-day result
or a later one, that test would fail.
"""

import pickle
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from app.features import (
    ALL_FEATURE_COLUMNS,
    FEATURE_COLUMNS,
    FORM_STATS,
    EloConfig,
    build_features,
    build_match_features,
    elo_ratings,
    expected_home_score,
    rolling_form,
    season_for_date,
)

# Six-team seasons. Team 6 goes down after the first season and team 7 comes up.
# Then team 5 goes down and team 6 comes back.
SEASON_TEAMS = {
    "2015-16": [1, 2, 3, 4, 5, 6],
    "2016-17": [1, 2, 3, 4, 5, 7],
    "2017-18": [1, 2, 3, 4, 6, 7],
}


def round_robin(teams: list[int]) -> list[list[tuple[int, int]]]:
    """Double round robin by the circle method: a list of rounds of (home, away) pairs."""
    n = len(teams)
    order = list(teams)
    first_half = []
    for _ in range(n - 1):
        first_half.append([(order[i], order[n - 1 - i]) for i in range(n // 2)])
        order = [order[0], order[-1], *order[1:-1]]
    second_half = [[(away, home) for home, away in rnd] for rnd in first_half]
    return first_half + second_half


def make_league(seed: int = 0) -> pd.DataFrame:
    """Fixtures for SEASON_TEAMS with random but valid results. One round per week,
    so every date has three matches at once, which exercises same-day handling."""
    rng = np.random.default_rng(seed)
    rows = []
    for season, teams in SEASON_TEAMS.items():
        start = date(int(season[:4]), 8, 1)
        for week, rnd in enumerate(round_robin(teams)):
            for home, away in rnd:
                rows.append(
                    {
                        "season": season,
                        "match_date": start + timedelta(weeks=week),
                        "home_team_id": home,
                        "away_team_id": away,
                    }
                )
    df = pd.DataFrame(rows)
    return with_random_results(df, df.index, rng)


def with_random_results(df: pd.DataFrame, rows: pd.Index, rng: np.random.Generator) -> pd.DataFrame:
    out = df.copy()
    n = len(rows)
    for side in ("home", "away"):
        goals = rng.integers(0, 5, n)
        out.loc[rows, f"{side}_goals"] = goals
        out.loc[rows, f"{side}_shots_on_target"] = goals + rng.integers(0, 6, n)
    for col in ("home_goals", "away_goals", "home_shots_on_target", "away_shots_on_target"):
        out[col] = out[col].astype("Int16")
    return out


def fixture(season: str, day: date, home: int, away: int, hg: int | None, ag: int | None) -> dict:
    return {
        "season": season,
        "match_date": day,
        "home_team_id": home,
        "away_team_id": away,
        "home_goals": hg,
        "away_goals": ag,
        "home_shots_on_target": None if hg is None else hg + 2,
        "away_shots_on_target": None if ag is None else ag + 1,
    }


def frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    for col in ("home_goals", "away_goals", "home_shots_on_target", "away_shots_on_target"):
        df[col] = df[col].astype("Int16")
    return df


# --- the leakage test ------------------------------------------------------------


@pytest.mark.parametrize("mode", ["rewrite", "blank"])
@pytest.mark.parametrize(
    "elo", [EloConfig(), EloConfig(k=30, season_regression=0.3, promoted_offset=-80)], ids=["v1", "v2"]
)
def test_no_feature_uses_the_match_itself_or_later(mode: str, elo: EloConfig) -> None:
    league = make_league(seed=1)
    baseline = build_features(league, elo)[ALL_FEATURE_COLUMNS]
    rng = np.random.default_rng(99)

    changed_somewhere = False
    for cutoff in sorted(league["match_date"].unique()):
        on_or_after = league.index[league["match_date"] >= cutoff]
        if mode == "rewrite":
            altered = with_random_results(league, on_or_after, rng)
        else:
            altered = league.copy()
            altered.loc[on_or_after, ["home_goals", "away_goals"]] = pd.NA
            altered.loc[on_or_after, ["home_shots_on_target", "away_shots_on_target"]] = pd.NA

        features = build_features(altered, elo)[ALL_FEATURE_COLUMNS]

        # Everything up to and including the cutoff date is unaffected...
        upto = league["match_date"] <= cutoff
        pd.testing.assert_frame_equal(features[upto], baseline[upto], check_exact=True)
        # ...while later matches do change, proving the alteration had teeth.
        later = ~upto
        if later.any() and not features[later].equals(baseline[later]):
            changed_somewhere = True

    assert changed_somewhere


def test_feature_rows_do_not_depend_on_input_order() -> None:
    league = make_league(seed=2)
    shuffled = league.sample(frac=1.0, random_state=0)
    pd.testing.assert_frame_equal(
        build_features(shuffled).loc[league.index], build_features(league)
    )


def test_result_is_not_a_feature() -> None:
    assert "result" not in ALL_FEATURE_COLUMNS
    assert not any("goals" == c or c.endswith("_goals") for c in ALL_FEATURE_COLUMNS)


def test_team_playing_twice_in_a_day_is_rejected() -> None:
    day = date(2015, 8, 8)
    df = frame([fixture("2015-16", day, 1, 2, 1, 0), fixture("2015-16", day, 3, 1, 0, 0)])
    with pytest.raises(ValueError, match="more than once"):
        build_features(df)


# --- Elo ---------------------------------------------------------------------------


def test_expected_score_includes_home_advantage() -> None:
    assert expected_home_score(1500, 1500, 0) == pytest.approx(0.5)
    assert expected_home_score(1500, 1500, 60) == pytest.approx(1 / (1 + 10 ** (-60 / 400)))
    assert expected_home_score(1500, 1900, 0) == pytest.approx(1 / 11)


def test_elo_hand_computed() -> None:
    cfg = EloConfig(initial=1500, k=20, home_advantage=60)
    d1, d2 = date(2015, 8, 8), date(2015, 8, 15)
    df = frame(
        [
            fixture("2015-16", d1, 1, 2, 2, 0),  # 1 beats 2 at home
            fixture("2015-16", d1, 3, 4, 1, 1),  # same day draw
            fixture("2015-16", d2, 2, 1, 0, 0),
        ]
    )
    elo = elo_ratings(df, cfg)

    # Nobody has played yet, so every first-day rating is the initial one.
    assert elo.loc[0].tolist() == [1500, 1500]
    assert elo.loc[1].tolist() == [1500, 1500]

    gain = 20 * (1 - expected_home_score(1500, 1500, 60))
    assert elo.loc[2, "home_elo"] == pytest.approx(1500 - gain)  # team 2 lost
    assert elo.loc[2, "away_elo"] == pytest.approx(1500 + gain)  # team 1 won


def test_elo_home_draw_costs_the_home_side() -> None:
    """With home advantage a draw is below expectation for the home team."""
    d1, d2 = date(2015, 8, 8), date(2015, 8, 15)
    df = frame([fixture("2015-16", d1, 1, 2, 0, 0), fixture("2015-16", d2, 1, 2, None, None)])
    elo = elo_ratings(df)
    assert elo.loc[1, "home_elo"] < 1500 < elo.loc[1, "away_elo"]


def test_unplayed_matches_get_ratings_but_do_not_move_them() -> None:
    d = [date(2015, 8, 8), date(2015, 8, 15), date(2015, 8, 22)]
    df = frame(
        [
            fixture("2015-16", d[0], 1, 2, 3, 0),
            fixture("2015-16", d[1], 1, 2, None, None),
            fixture("2015-16", d[2], 1, 2, None, None),
        ]
    )
    elo = elo_ratings(df)
    assert elo.loc[1].tolist() == elo.loc[2].tolist()
    assert elo.loc[1, "home_elo"] > 1500


def test_promoted_teams_start_at_relegated_teams_average() -> None:
    e = expected_home_score(1500, 1500, 60)
    df = frame(
        [
            # 2015-16: teams 1-4. Team 3 loses 3-0 away, team 4 draws away.
            fixture("2015-16", date(2016, 5, 1), 1, 3, 3, 0),
            fixture("2015-16", date(2016, 5, 1), 2, 4, 0, 0),
            # 2016-17: 3 and 4 relegated, 5 and 6 promoted.
            fixture("2016-17", date(2016, 8, 13), 5, 1, None, None),
            fixture("2016-17", date(2016, 8, 13), 6, 2, None, None),
            # 2017-18: 5 relegated (never played, so still at its starting rating), 3 returns.
            fixture("2017-18", date(2017, 8, 12), 3, 1, None, None),
            fixture("2017-18", date(2017, 8, 12), 6, 2, None, None),
        ]
    )
    elo = elo_ratings(df)
    team3_end = 1500 - 20 * (1 - e)  # away loss: the home side's gain
    team4_end = 1500 + 20 * (e - 0.5)  # away draw: the home side fell short of e
    promoted = (team3_end + team4_end) / 2

    assert elo.loc[2, "home_elo"] == pytest.approx(promoted)  # team 5
    assert elo.loc[3, "home_elo"] == pytest.approx(promoted)  # team 6
    # Team 3 comes back at the rating of the team it replaces (5), not its stale old one.
    assert elo.loc[4, "home_elo"] == pytest.approx(promoted)
    assert elo.loc[4, "home_elo"] != pytest.approx(team3_end)


def two_season_league() -> pd.DataFrame:
    """2015-16: 1 beats 3 and 2 beats 4. 2016-17: 4 relegated, 5 promoted."""
    return frame(
        [
            fixture("2015-16", date(2016, 5, 1), 1, 3, 3, 0),
            fixture("2015-16", date(2016, 5, 1), 2, 4, 2, 0),
            fixture("2016-17", date(2016, 8, 13), 1, 2, None, None),
            fixture("2016-17", date(2016, 8, 13), 3, 5, None, None),
        ]
    )


def test_season_regression_pulls_ratings_towards_the_average() -> None:
    league = two_season_league()
    carried = elo_ratings(league).loc[2:3]
    pulled = elo_ratings(league, EloConfig(season_regression=0.4)).loc[2:3]
    # All four 2015-16 teams average 1500 (Elo is zero-sum), so a 40% pull
    # leaves 60% of each team's gap to 1500.
    for team_rating, pulled_rating in [
        (carried.loc[2, "home_elo"], pulled.loc[2, "home_elo"]),  # team 1
        (carried.loc[3, "home_elo"], pulled.loc[3, "home_elo"]),  # team 3
    ]:
        assert pulled_rating - 1500 == pytest.approx(0.6 * (team_rating - 1500))


def test_promoted_offset_shifts_the_promoted_starting_rating() -> None:
    league = two_season_league()
    base = elo_ratings(league).loc[3, "away_elo"]  # team 5 = relegated team 4's rating
    lower = elo_ratings(league, EloConfig(promoted_offset=-100)).loc[3, "away_elo"]
    assert lower == pytest.approx(base - 100)


def test_promoted_rating_uses_ratings_after_the_pull() -> None:
    league = two_season_league()
    cfg = EloConfig(season_regression=0.5, promoted_offset=-50)
    team4_end = elo_ratings(league).loc[3, "away_elo"]
    assert elo_ratings(league, cfg).loc[3, "away_elo"] == pytest.approx(
        1500 + 0.5 * (team4_end - 1500) - 50
    )


def test_elo_config_pickled_before_the_new_fields_still_loads() -> None:
    """The v1 model file stores an EloConfig without season_regression or promoted_offset."""
    old = object.__new__(EloConfig)
    object.__setattr__(old, "__dict__", {"initial": 1500.0, "k": 20.0, "home_advantage": 60.0})
    restored = pickle.loads(pickle.dumps(old))
    assert restored.season_regression == 0.0 and restored.promoted_offset == 0.0
    league = make_league(seed=4)
    pd.testing.assert_frame_equal(elo_ratings(league, restored), elo_ratings(league))


# --- difference features -----------------------------------------------------------


def test_differences_are_home_minus_away() -> None:
    features = build_features(make_league(seed=5))
    np.testing.assert_allclose(features["elo_diff"], features["home_elo"] - features["away_elo"])
    for stat in FORM_STATS:
        np.testing.assert_allclose(
            features[f"form_{stat}_diff"],
            features[f"home_form_{stat}"] - features[f"away_form_{stat}"],
        )
    assert set(ALL_FEATURE_COLUMNS) <= set(features.columns)


def test_first_season_teams_all_start_equal() -> None:
    league = make_league(seed=4)
    first_date = league["match_date"].min()
    first = elo_ratings(league)[league["match_date"] == first_date]
    assert (first.to_numpy() == 1500).all()


# --- rolling form ------------------------------------------------------------------


def test_form_is_average_of_previous_five_matches() -> None:
    # Team 1 plays seven times at home against different opponents with known scores.
    scores = [(1, 0), (0, 0), (2, 3), (4, 1), (0, 2), (1, 1), (9, 9)]
    rows = [
        fixture("2015-16", date(2015, 8, 1) + timedelta(weeks=i), 1, 10 + i, hg, ag)
        for i, (hg, ag) in enumerate(scores)
    ]
    form = rolling_form(frame(rows))

    # Going into the 7th match, the window is matches 2..6.
    window = scores[1:6]
    assert form.loc[6, "home_form_goals_for"] == pytest.approx(np.mean([h for h, _ in window]))
    assert form.loc[6, "home_form_goals_against"] == pytest.approx(np.mean([a for _, a in window]))
    points = [3 if h > a else 1 if h == a else 0 for h, a in window]
    assert form.loc[6, "home_form_points"] == pytest.approx(np.mean(points))
    # Shots on target in `fixture` are goals + 2 for, goals + 1 against.
    assert form.loc[6, "home_form_sot_for"] == pytest.approx(np.mean([h + 2 for h, _ in window]))
    assert form.loc[6, "home_form_sot_against"] == pytest.approx(np.mean([a + 1 for _, a in window]))
    # Going into the 2nd match, only the 1st counts (a 1-0 win).
    assert form.loc[1, "home_form_points"] == 3


def test_form_is_missing_for_a_teams_first_match() -> None:
    form = rolling_form(frame([fixture("2015-16", date(2015, 8, 8), 1, 2, 1, 0)]))
    assert form.isna().all(axis=None)


def test_form_counts_home_and_away_matches_from_the_teams_side() -> None:
    d = [date(2015, 8, 8), date(2015, 8, 15), date(2015, 8, 22)]
    df = frame(
        [
            fixture("2015-16", d[0], 1, 2, 2, 0),  # team 2 loses away 2-0
            fixture("2015-16", d[1], 2, 3, 1, 1),  # team 2 draws at home 1-1
            fixture("2015-16", d[2], 4, 2, None, None),
        ]
    )
    form = rolling_form(df)
    assert form.loc[2, "away_form_points"] == pytest.approx(0.5)  # (0 + 1) / 2
    assert form.loc[2, "away_form_goals_for"] == pytest.approx(0.5)  # (0 + 1) / 2
    assert form.loc[2, "away_form_goals_against"] == pytest.approx(1.5)  # (2 + 1) / 2


def test_form_carries_across_seasons() -> None:
    df = frame(
        [
            fixture("2015-16", date(2016, 5, 1), 1, 2, 3, 0),
            fixture("2016-17", date(2016, 8, 13), 1, 3, None, None),
        ]
    )
    assert rolling_form(df).loc[1, "home_form_points"] == 3


def test_build_features_output_shape() -> None:
    league = make_league(seed=5)
    features = build_features(league)
    assert list(features.index) == list(league.index)
    assert set(FEATURE_COLUMNS) <= set(features.columns)
    assert set(features["result"].dropna()) <= {"H", "D", "A"}
    # Elo is always defined; form is missing only for each team's very first match.
    assert features[["home_elo", "away_elo"]].notna().all(axis=None)
    missing_form = features["home_form_points"].isna().sum() + features["away_form_points"].isna().sum()
    assert missing_form == league[["home_team_id", "away_team_id"]].stack().nunique()


# --- hypothetical matches (serving) ------------------------------------------------


def test_hypothetical_match_features_equal_training_features() -> None:
    """No training/serving skew: asking for a hypothetical match between the same
    teams on the same date gives exactly the features training built for the real one."""
    league = make_league(seed=6)
    training = build_features(league)[ALL_FEATURE_COLUMNS]
    for i, m in league.iterrows():
        served = build_match_features(league, m["home_team_id"], m["away_team_id"], m["match_date"])
        pd.testing.assert_series_equal(served, training.loc[i].astype(float), check_names=False)


def test_hypothetical_match_ignores_results_on_or_after_as_of() -> None:
    league = make_league(seed=7)
    as_of = sorted(league["match_date"].unique())[12]
    before = build_match_features(league, 1, 2, as_of)
    rescored = with_random_results(
        league, league.index[league["match_date"] >= as_of], np.random.default_rng(3)
    )
    pd.testing.assert_series_equal(build_match_features(rescored, 1, 2, as_of), before)


def test_hypothetical_match_uses_settings_passed_in() -> None:
    league = make_league(seed=8)
    as_of = league["match_date"].max() + timedelta(days=7)
    default = build_match_features(league, 1, 2, as_of)
    custom = build_match_features(league, 1, 2, as_of, EloConfig(k=40), form_window=2)
    assert custom["home_elo"] != default["home_elo"]
    assert custom["home_form_points"] != default["home_form_points"]


def test_hypothetical_match_for_a_team_with_no_history_has_missing_form() -> None:
    league = make_league(seed=9)
    features = build_match_features(league, 1, 99, league["match_date"].max() + timedelta(days=7))
    assert features[[c for c in FEATURE_COLUMNS if c.startswith("away_form")]].isna().all()
    assert not np.isnan(features["away_elo"])


def test_hypothetical_match_rejects_a_team_playing_itself() -> None:
    with pytest.raises(ValueError, match="differ"):
        build_match_features(make_league(), 1, 1, date(2018, 1, 1))


@pytest.mark.parametrize(
    "day,season",
    [(date(2026, 9, 23), "2026-27"), (date(2027, 5, 20), "2026-27"), (date(2026, 7, 1), "2026-27"),
     (date(2026, 6, 30), "2025-26"), (date(2009, 8, 1), "2009-10")],
)
def test_season_for_date(day: date, season: str) -> None:
    assert season_for_date(day) == season
