"""Pre-match features for the match outcome model.

Every feature for a match is computed only from matches played on an earlier
date. Nothing from the match itself, from other matches the same day, or from
anything later can reach it. Two mechanisms enforce this:

* Elo: matches are processed one date at a time. All matches on a date read the
  ratings as they stood before that date, and only then are that date's
  results applied.
* Form: a rolling snapshot is taken after each team's match, and each fixture
  looks up the latest snapshot with `merge_asof(..., allow_exact_matches=False)`,
  i.e. strictly before its own date.

`tests/test_features.py` checks this by scrambling the result of each match and
everything after it and asserting the match's features do not change.

Pure pandas and numpy, no database access.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = [
    "season",
    "match_date",
    "home_team_id",
    "away_team_id",
    "home_goals",
    "away_goals",
    "home_shots_on_target",
    "away_shots_on_target",
]
FORM_STATS = ["points", "goals_for", "goals_against", "sot_for", "sot_against"]
FORM_WINDOW = 5
FEATURE_COLUMNS = [
    "home_elo",
    "away_elo",
    *(f"{side}_form_{stat}" for side in ("home", "away") for stat in FORM_STATS),
]


@dataclass(frozen=True)
class EloConfig:
    """Elo parameters. Ratings are on the usual chess-style scale.

    Attributes:
        initial: Rating every team starts with in the first season.
        k: How far one result moves a rating. Higher reacts faster but is noisier.
        home_advantage: Rating points added to the home side when working out
            the expected result.
    """

    initial: float = 1500.0
    k: float = 20.0
    home_advantage: float = 60.0


def expected_home_score(home_elo: float, away_elo: float, home_advantage: float) -> float:
    """Elo's expected score for the home side: 1 = certain win, 0.5 = even."""
    return float(1.0 / (1.0 + 10.0 ** ((away_elo - home_elo - home_advantage) / 400.0)))


def match_results(matches: pd.DataFrame) -> pd.Series:
    """Full-time result per match: "H", "D" or "A". <NA> for unplayed matches."""
    diff = (matches["home_goals"] - matches["away_goals"]).astype("Float64")
    result = pd.Series(pd.NA, index=matches.index, dtype="string")
    result[diff.gt(0).fillna(False)] = "H"
    result[diff.eq(0).fillna(False)] = "D"
    result[diff.lt(0).fillna(False)] = "A"
    return result


def _check_columns(matches: pd.DataFrame) -> None:
    missing = set(REQUIRED_COLUMNS) - set(matches.columns)
    if missing:
        raise ValueError(f"matches is missing columns: {sorted(missing)}")


def elo_ratings(matches: pd.DataFrame, config: EloConfig = EloConfig()) -> pd.DataFrame:
    """Each team's Elo rating going into each match.

    Promoted teams (in this season's fixtures but not last season's) start the
    season at the average rating of the teams they replaced. Otherwise a promoted
    side would enter at 1500, far above where it belongs, or keep a stale rating
    from years earlier. Only the fixture list is used to spot them, and it is
    published before the season starts.

    Unplayed matches still get pre-match ratings. They just don't update anything.

    Args:
        matches: One row per fixture with at least REQUIRED_COLUMNS.
        config: Elo parameters.

    Returns:
        Columns `home_elo` and `away_elo`, same index as `matches`.
    """
    _check_columns(matches)
    home_ids = matches["home_team_id"].to_numpy()
    away_ids = matches["away_team_id"].to_numpy()
    home_goals = matches["home_goals"].astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    away_goals = matches["away_goals"].astype("Float64").to_numpy(dtype=float, na_value=np.nan)
    home_elo = np.full(len(matches), np.nan)
    away_elo = np.full(len(matches), np.nan)

    ratings: dict[int, float] = {}
    previous_teams: set[int] = set()
    dates = pd.to_datetime(matches["match_date"])
    season_order = dates.groupby(matches["season"]).min().sort_values().index

    for season in season_order:
        in_season = (matches["season"] == season).to_numpy()
        teams = set(home_ids[in_season]) | set(away_ids[in_season])
        relegated = previous_teams - teams
        promoted_rating = (
            float(np.mean([ratings[t] for t in relegated])) if relegated else config.initial
        )
        for team in teams - previous_teams:
            ratings[team] = promoted_rating if previous_teams else config.initial
        previous_teams = teams

        # Positional row numbers for this season, grouped by date in date order.
        season_dates = dates[in_season]
        positions = np.flatnonzero(in_season)
        for _, rows in pd.Series(positions, index=season_dates.values).groupby(level=0):
            rows_np = rows.to_numpy()
            # 1) Read every match's pre-match ratings before any result that day is applied.
            for i in rows_np:
                home_elo[i] = ratings[home_ids[i]]
                away_elo[i] = ratings[away_ids[i]]
            # 2) Apply that day's results.
            for i in rows_np:
                if np.isnan(home_goals[i]) or np.isnan(away_goals[i]):
                    continue
                actual = 0.5 * (1.0 + np.sign(home_goals[i] - away_goals[i]))
                expected = expected_home_score(home_elo[i], away_elo[i], config.home_advantage)
                delta = config.k * (actual - expected)
                ratings[home_ids[i]] += delta
                ratings[away_ids[i]] -= delta

    return pd.DataFrame({"home_elo": home_elo, "away_elo": away_elo}, index=matches.index)


def team_match_log(matches: pd.DataFrame) -> pd.DataFrame:
    """Played matches in long format: one row per team per match, from that team's side.

    Columns: team_id, match_date (datetime64), plus FORM_STATS.
    """
    _check_columns(matches)
    played = matches[matches["home_goals"].notna() & matches["away_goals"].notna()]

    def side(team: str, gf: str, ga: str, sf: str, sa: str) -> pd.DataFrame:
        goals_for = played[gf].astype(float)
        goals_against = played[ga].astype(float)
        points = np.select(
            [goals_for > goals_against, goals_for == goals_against], [3.0, 1.0], default=0.0
        )
        return pd.DataFrame(
            {
                "team_id": played[team].to_numpy(),
                "match_date": pd.to_datetime(played["match_date"]).to_numpy(),
                "points": points,
                "goals_for": goals_for.to_numpy(),
                "goals_against": goals_against.to_numpy(),
                "sot_for": played[sf].astype("Float64").to_numpy(dtype=float, na_value=np.nan),
                "sot_against": played[sa].astype("Float64").to_numpy(dtype=float, na_value=np.nan),
            }
        )

    home_sot, away_sot = "home_shots_on_target", "away_shots_on_target"
    home = side("home_team_id", "home_goals", "away_goals", home_sot, away_sot)
    away = side("away_team_id", "away_goals", "home_goals", away_sot, home_sot)
    return (
        pd.concat([home, away], ignore_index=True)
        .sort_values(["team_id", "match_date"], kind="stable")
        .reset_index(drop=True)
    )


def rolling_form(matches: pd.DataFrame, window: int = FORM_WINDOW) -> pd.DataFrame:
    """Average points, goals and shots on target over each team's last `window` matches.

    Uses the team's most recent league matches before the fixture's date, even
    across seasons, so a promoted team's form comes from its last Premier League
    spell. A team with no earlier matches in the data gets NaN (the model imputes).

    Returns:
        Columns `{home,away}_form_{stat}` for each stat in FORM_STATS, same index as `matches`.
    """
    log = team_match_log(matches)
    out = pd.DataFrame(index=matches.index)
    if log.empty:  # nothing played yet, e.g. a fixture list before the season starts
        for side in ("home", "away"):
            for stat in FORM_STATS:
                out[f"{side}_form_{stat}"] = np.nan
        return out

    # Form *after* each match, i.e. what the team carries into its next one.
    snapshots = log[["team_id", "match_date"]].copy()
    snapshots[FORM_STATS] = log.groupby("team_id")[FORM_STATS].transform(
        lambda s: s.rolling(window, min_periods=1).mean()
    )
    snapshots = snapshots.sort_values("match_date", kind="stable")

    for side in ("home", "away"):
        queries = pd.DataFrame(
            {
                "row": np.arange(len(matches)),
                "team_id": matches[f"{side}_team_id"].to_numpy(),
                "match_date": pd.to_datetime(matches["match_date"]).to_numpy(),
            }
        ).sort_values("match_date", kind="stable")
        # allow_exact_matches=False: only snapshots from strictly earlier dates qualify,
        # so neither this match nor anything else on the same day can leak in.
        found = pd.merge_asof(
            queries,
            snapshots,
            on="match_date",
            by="team_id",
            allow_exact_matches=False,
            direction="backward",
        ).sort_values("row")
        for stat in FORM_STATS:
            out[f"{side}_form_{stat}"] = found[stat].to_numpy()
    return out


def build_features(matches: pd.DataFrame, elo: EloConfig = EloConfig()) -> pd.DataFrame:
    """Model inputs for every match, plus the result to predict.

    Args:
        matches: One row per fixture with at least REQUIRED_COLUMNS, any order.
        elo: Elo parameters.

    Returns:
        Same index as `matches`, with `season`, `match_date`, FEATURE_COLUMNS and
        `result` ("H"/"D"/"A", <NA> if unplayed).
    """
    _check_columns(matches)
    # "Before this date" only equals "before this match" if no team plays twice in a day.
    appearances = pd.concat(
        [
            matches[["match_date", side]].set_axis(["match_date", "team_id"], axis=1)
            for side in ("home_team_id", "away_team_id")
        ]
    )
    if appearances.duplicated().any():
        raise ValueError("a team plays more than once on the same date")
    features = pd.concat(
        [
            matches[["season", "match_date"]],
            elo_ratings(matches, elo),
            rolling_form(matches),
        ],
        axis=1,
    )
    features["result"] = match_results(matches)
    return features
