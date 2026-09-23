"""Parse and clean Premier League result CSVs from football-data.co.uk.

Pure pandas, no database or network access, so it can be unit-tested with a
small sample file. See `scripts/load_history.py` for the download and insert.
"""

from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import IO

import pandas as pd

# CSV column -> matches table column. Every other column in the file is ignored.
COLUMN_MAP: dict[str, str] = {
    "Date": "match_date",
    "HomeTeam": "home_team",
    "AwayTeam": "away_team",
    "FTHG": "home_goals",
    "FTAG": "away_goals",
    "HS": "home_shots",
    "AS": "away_shots",
    "HST": "home_shots_on_target",
    "AST": "away_shots_on_target",
}
# Bet365 pre-match decimal odds. Optional: a file without them loads with NULL odds.
ODDS_COLUMN_MAP: dict[str, str] = {
    "B365H": "odds_home",
    "B365D": "odds_draw",
    "B365A": "odds_away",
}
STAT_COLUMNS = [
    "home_goals",
    "away_goals",
    "home_shots",
    "away_shots",
    "home_shots_on_target",
    "away_shots_on_target",
]
ODDS_COLUMNS = list(ODDS_COLUMN_MAP.values())
OUTPUT_COLUMNS = [
    "season",
    "match_date",
    "home_team_id",
    "away_team_id",
    *STAT_COLUMNS,
    *ODDS_COLUMNS,
]


def season_label(code: str) -> str:
    """Turn football-data's four-digit season code into our label.

    Args:
        code: Season code as used in the URL, e.g. "2425".

    Returns:
        Season label, e.g. "2024-25".
    """
    if len(code) != 4 or not code.isdigit():
        raise ValueError(f"Season code must be four digits like '2425', got {code!r}")
    start, end = int(code[:2]), int(code[2:])
    if (start + 1) % 100 != end:
        raise ValueError(f"Season code {code!r} does not span consecutive years")
    return f"20{code[:2]}-{code[2:]}"


def season_code(label: str) -> str:
    """Inverse of `season_label`: "2024-25" -> "2425"."""
    code = label[2:4] + label[5:7]
    if season_label(code) != label:
        raise ValueError(f"Season label must look like '2024-25', got {label!r}")
    return code


def normalize_team_name(name: str) -> str:
    """Key used to look a team name up in the alias table.

    Case and runs of whitespace are ignored, so " man  united" matches "Man United".
    """
    return " ".join(name.split()).casefold()


def read_raw_csv(source: Path | IO[bytes]) -> pd.DataFrame:
    """Read a football-data.co.uk results CSV, keeping only the columns we load.

    Newer files start with a UTF-8 byte-order mark; `utf-8-sig` strips it so the
    first header is "Div", not "\\ufeffDiv". Everything is read as text so that
    cleaning, not the CSV parser, decides how each column is typed. Odds columns
    the file lacks are added as empty, since odds are optional.
    """
    raw = pd.read_csv(source, encoding="utf-8-sig", dtype=str, skipinitialspace=True)
    missing = set(COLUMN_MAP) - set(raw.columns)
    if missing:
        raise ValueError(f"CSV is missing expected columns: {sorted(missing)}")
    # Added columns come back as float NaN; keep them object like the rest, for `.str`.
    raw = raw.reindex(columns=[*COLUMN_MAP, *ODDS_COLUMN_MAP]).astype(object)
    # Some files end with empty rows or trailing commas; drop rows with no data at all.
    return raw.dropna(how="all").reset_index(drop=True)


def parse_match_dates(raw: pd.Series) -> pd.Series:
    """Parse day-first dates, which appear as both "13/08/2016" and "13/08/16".

    Each format is parsed explicitly (never guessed), so "01/02/2016" is always
    1 February, never 2 January.

    Raises:
        ValueError: If any value matches neither format.
    """
    text = raw.str.strip()
    four_digit_year = text.str.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", na=False)
    parsed = pd.to_datetime(text.where(four_digit_year), format="%d/%m/%Y", errors="coerce")
    parsed = parsed.fillna(
        pd.to_datetime(text.where(~four_digit_year), format="%d/%m/%y", errors="coerce")
    )
    bad = raw[parsed.isna()]
    if not bad.empty:
        raise ValueError(f"Unparseable match dates: {bad.tolist()}")
    return parsed.dt.date


def map_team_ids(names: pd.Series, alias_to_id: Mapping[str, int]) -> pd.Series:
    """Resolve source team names to team ids through the alias table.

    Args:
        names: Team names as written in the source file.
        alias_to_id: Alias -> team id, i.e. the contents of the team_aliases table.

    Raises:
        ValueError: If any name has no alias. Unknown names fail loudly instead of
            silently creating a second copy of a team; add the alias and rerun.
    """
    lookup = {normalize_team_name(alias): team_id for alias, team_id in alias_to_id.items()}
    ids = names.map(lambda n: lookup.get(normalize_team_name(n)) if isinstance(n, str) else None)
    unknown = sorted(set(names[ids.isna()].astype(str)))
    if unknown:
        raise ValueError(f"Unknown team names (add them to the alias table): {unknown}")
    return ids.astype("int64")


def _check_dates_in_season(dates: pd.Series, season: str) -> None:
    """Catch day/month or century mix-ups: every date must fall in the season's window.

    The window runs 1 July to 31 July of the next year, because the 2019-20 season
    was paused for COVID and finished on 26 July 2020.
    """
    start_year = int(season[:4])
    lo, hi = date(start_year, 7, 1), date(start_year + 1, 7, 31)
    outside = dates[(dates < lo) | (dates > hi)]
    if not outside.empty:
        raise ValueError(f"{season}: dates outside {lo}..{hi}: {sorted(set(outside))}")


def clean_results(raw: pd.DataFrame, season: str, alias_to_id: Mapping[str, int]) -> pd.DataFrame:
    """Turn a raw football-data CSV into rows shaped like the matches table.

    Args:
        raw: Output of `read_raw_csv`.
        season: Season label, e.g. "2024-25".
        alias_to_id: Alias -> team id, from the team_aliases table.

    Returns:
        One row per fixture with the columns in `OUTPUT_COLUMNS`. Goals and shots
        use the nullable Int16 dtype: blank cells (unplayed fixtures) become <NA>.

    Raises:
        ValueError: On unknown teams, bad dates, non-numeric stats, or a fixture
            that appears twice.
    """
    df = raw.rename(columns={**COLUMN_MAP, **ODDS_COLUMN_MAP})

    cleaned = pd.DataFrame(
        {
            "season": season,
            "match_date": parse_match_dates(df["match_date"]),
            "home_team_id": map_team_ids(df["home_team"], alias_to_id),
            "away_team_id": map_team_ids(df["away_team"], alias_to_id),
        }
    )
    for col in STAT_COLUMNS:
        # errors="raise": a stray "abc" should stop the load, not become NULL.
        cleaned[col] = pd.to_numeric(df[col].str.strip(), errors="raise").astype("Int16")
    for col in ODDS_COLUMNS:
        cleaned[col] = pd.to_numeric(df[col].str.strip(), errors="raise").astype("Float64")
        # Decimal odds include the returned stake, so a real price is always above 1.0.
        bad_odds = cleaned[col].le(1.0).fillna(False)
        if bad_odds.any():
            rows = bad_odds[bad_odds].index.tolist()
            raise ValueError(f"{season}: {col} must be above 1.0, bad rows {rows}")

    _check_dates_in_season(cleaned["match_date"], season)

    same_team = cleaned["home_team_id"] == cleaned["away_team_id"]
    if same_team.any():
        rows = same_team[same_team].index.tolist()
        raise ValueError(f"{season}: team listed as playing itself in rows {rows}")

    dupes = cleaned.duplicated(["home_team_id", "away_team_id"], keep=False)
    if dupes.any():
        raise ValueError(f"{season}: duplicate fixtures in rows {dupes[dupes].index.tolist()}")

    return cleaned[OUTPUT_COLUMNS]


def to_records(df: pd.DataFrame) -> list[dict[str, object]]:
    """Convert cleaned rows to plain dicts for the database driver.

    asyncpg cannot bind pandas' <NA> or numpy integer types, so values become
    plain Python ints and missing values become None.
    """
    as_objects = df.astype(object)
    return as_objects.where(df.notna(), None).to_dict("records")  # type: ignore[return-value]
