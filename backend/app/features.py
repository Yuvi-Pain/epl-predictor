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
from datetime import date

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
# Per-team features: what the v1 model trains on and what the API shows.
FEATURE_COLUMNS = [
    "home_elo",
    "away_elo",
    *(f"{side}_form_{stat}" for side in ("home", "away") for stat in FORM_STATS),
]
# Home minus away for each of the above: what v2 trains on. A model on these only
# sees the gap between the teams, so two equal teams get the same prediction
# whether both are rated 1300 or 1800, and the home advantage is the intercept.
DIFF_FEATURE_COLUMNS = ["elo_diff", *(f"form_{stat}_diff" for stat in FORM_STATS)]
ALL_FEATURE_COLUMNS = [*FEATURE_COLUMNS, *DIFF_FEATURE_COLUMNS]


@dataclass(frozen=True)
class EloConfig:
    """Elo parameters. Ratings are on the usual chess-style scale.

    Attributes:
        initial: Rating every team starts with in the first season.
        k: How far one result moves a rating. Higher reacts faster but is noisier.
        home_advantage: Rating points added to the home side when working out
            the expected result.
        season_regression: Share of each team's gap to the league average removed
            between seasons, to allow for summer transfers and managers.
            0 carries ratings over unchanged; 0.3 pulls every team 30% of the
            way back to the average.
        promoted_offset: Rating points added to the relegated teams' average to
            get the promoted teams' starting rating. Negative starts them below
            the sides they replace.
    """

    initial: float = 1500.0
    k: float = 20.0
    home_advantage: float = 60.0
    # Defaults reproduce v1, which had neither. Models pickled before these fields
    # existed still load: a missing attribute falls back to this class default.
    season_regression: float = 0.0
    promoted_offset: float = 0.0


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

    Between seasons, every team that stayed up is pulled `season_regression` of
    the way towards last season's average rating.

    Promoted teams (in this season's fixtures but not last season's) then start
    the season at the average rating of the teams they replaced, plus
    `promoted_offset`. Otherwise a promoted side would enter at 1500, far above
    where it belongs, or keep a stale rating from years earlier. Only the
    fixture list is used to spot them, and it is published before the season
    starts.

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
        if previous_teams and config.season_regression:
            average = float(np.mean([ratings[t] for t in previous_teams]))
            for team in previous_teams:
                ratings[team] -= config.season_regression * (ratings[team] - average)
        promoted_rating = (
            float(np.mean([ratings[t] for t in relegated])) + config.promoted_offset
            if relegated
            else config.initial
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


def add_difference_features(features: pd.DataFrame) -> pd.DataFrame:
    """Add DIFF_FEATURE_COLUMNS (home minus away) to a frame holding FEATURE_COLUMNS.

    A difference is NaN if either side is (e.g. a team with no earlier matches).
    """
    out = features.copy()
    out["elo_diff"] = out["home_elo"] - out["away_elo"]
    for stat in FORM_STATS:
        out[f"form_{stat}_diff"] = out[f"home_form_{stat}"] - out[f"away_form_{stat}"]
    return out


def build_features(
    matches: pd.DataFrame, elo: EloConfig = EloConfig(), form_window: int = FORM_WINDOW
) -> pd.DataFrame:
    """Model inputs for every match, plus the result to predict.

    Args:
        matches: One row per fixture with at least REQUIRED_COLUMNS, any order.
        elo: Elo parameters.
        form_window: How many recent matches the form averages cover.

    Returns:
        Same index as `matches`, with `season`, `match_date`, ALL_FEATURE_COLUMNS
        and `result` ("H"/"D"/"A", <NA> if unplayed).
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
    features = add_difference_features(
        pd.concat(
            [
                matches[["season", "match_date"]],
                elo_ratings(matches, elo),
                rolling_form(matches, form_window),
            ],
            axis=1,
        )
    )
    features["result"] = match_results(matches)
    return features


def season_for_date(day: date) -> str:
    """Season label a date belongs to: July onwards starts a new season.

    >>> season_for_date(date(2026, 9, 23))
    '2026-27'
    """
    start = day.year if day.month >= 7 else day.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def build_match_features(
    history: pd.DataFrame,
    home_team_id: int,
    away_team_id: int,
    as_of: date,
    elo: EloConfig = EloConfig(),
    form_window: int = FORM_WINDOW,
) -> pd.Series:
    """Features for a hypothetical match between two teams on `as_of`.

    Rather than re-deriving Elo and form separately for serving, this adds the
    hypothetical fixture to the match history and runs `build_features`, the
    exact function the model was trained on. So a live prediction sees the same
    features the model would have seen for a real match with these teams on
    this date. `tests/test_features.py` checks the two agree on real matches.

    Results on or after `as_of` are blanked, not dropped: they must not feed
    the features, but the fixtures still tell Elo which teams are in the season
    (for promoted sides), as they did in training. Any match either team plays
    on `as_of` is replaced by the hypothetical one, since a team cannot play
    twice in a day.

    Limitation: before a season's first match is in the data, there is no
    fixture list for it, so a promoted team's starting Elo is estimated from
    only the two teams in the hypothetical fixture.

    Args:
        history: Matches with at least REQUIRED_COLUMNS, e.g. the whole table.
        home_team_id: Home side.
        away_team_id: Away side. Must differ from the home side.
        as_of: Match date. Only results from strictly earlier dates are used.
        elo: Elo parameters. Pass the ones the model was trained with.
        form_window: Form window. Pass the one the model was trained with.

    Returns:
        ALL_FEATURE_COLUMNS for the hypothetical match. NaN where a team has no
        earlier matches (the model's imputer fills those, as in training).
    """
    _check_columns(history)
    if home_team_id == away_team_id:
        raise ValueError("home and away teams must differ")

    dates = pd.to_datetime(history["match_date"])
    as_of_ts = pd.Timestamp(as_of)
    playing = history["home_team_id"].isin([home_team_id, away_team_id]) | history[
        "away_team_id"
    ].isin([home_team_id, away_team_id])
    matches = history[~((dates == as_of_ts) & playing)].copy()
    result_columns = ["home_goals", "away_goals", "home_shots_on_target", "away_shots_on_target"]
    matches.loc[pd.to_datetime(matches["match_date"]) >= as_of_ts, result_columns] = pd.NA

    fixture = pd.DataFrame(
        [
            {
                "season": season_for_date(as_of),
                "match_date": as_of,
                "home_team_id": home_team_id,
                "away_team_id": away_team_id,
                **dict.fromkeys(result_columns, pd.NA),
            }
        ]
    )
    # Keep the history's dtypes (e.g. nullable Int16) so the fixture concatenates cleanly.
    fixture = fixture.astype({c: matches[c].dtype for c in fixture.columns if c in matches})
    combined = pd.concat([matches, fixture], ignore_index=True)
    features = build_features(combined, elo, form_window)
    return features.iloc[-1][ALL_FEATURE_COLUMNS].astype(float)
