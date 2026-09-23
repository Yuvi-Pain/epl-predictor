"""Cleaning tests for football-data.co.uk CSVs. Uses a small sample file; no network or database."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from app.football_data import (
    OUTPUT_COLUMNS,
    clean_results,
    map_team_ids,
    parse_match_dates,
    read_raw_csv,
    season_code,
    season_label,
    to_records,
)
from app.teams import KNOWN_TEAMS

SAMPLE_CSV = Path(__file__).parent / "fixtures" / "sample_E0.csv"

# Stand-in for the team_aliases table: every known spelling -> a fake team id.
TEAM_IDS = {name: i for i, name in enumerate(KNOWN_TEAMS, start=1)}
ALIAS_TO_ID = {
    alias: TEAM_IDS[name] for name, others in KNOWN_TEAMS.items() for alias in [name, *others]
}


@pytest.fixture
def cleaned() -> pd.DataFrame:
    return clean_results(read_raw_csv(SAMPLE_CSV), "2024-25", ALIAS_TO_ID)


# --- reading -------------------------------------------------------------------


def test_read_strips_bom_drops_blank_rows_and_extra_columns() -> None:
    raw = read_raw_csv(SAMPLE_CSV)
    assert raw.columns[0] == "Date"  # BOM stripped, so the first header is clean
    assert "B365H" not in raw.columns
    assert len(raw) == 4  # the trailing all-empty row is gone


def test_read_rejects_file_missing_columns(tmp_path: Path) -> None:
    bad = tmp_path / "bad.csv"
    bad.write_text("Div,Date,HomeTeam,AwayTeam\nE0,16/08/2024,Arsenal,Chelsea\n")
    with pytest.raises(ValueError, match="missing expected columns"):
        read_raw_csv(bad)


# --- team name mapping ---------------------------------------------------------


def test_team_names_map_to_canonical_ids(cleaned: pd.DataFrame) -> None:
    first = cleaned.iloc[0]
    assert first["home_team_id"] == TEAM_IDS["Manchester United"]  # "Man United"
    assert first["away_team_id"] == TEAM_IDS["Fulham"]
    assert cleaned.iloc[2]["home_team_id"] == TEAM_IDS["Nottingham Forest"]  # "Nott'm Forest"
    assert cleaned.iloc[2]["away_team_id"] == TEAM_IDS["Wolverhampton Wanderers"]  # "  Wolves "


@pytest.mark.parametrize("spelling", ["Man United", "man united", "  MAN   UNITED ", "Man Utd"])
def test_alias_lookup_ignores_case_and_whitespace(spelling: str) -> None:
    ids = map_team_ids(pd.Series([spelling]), ALIAS_TO_ID)
    assert ids.tolist() == [TEAM_IDS["Manchester United"]]


def test_unknown_team_fails_loudly_and_names_it() -> None:
    with pytest.raises(ValueError, match="Wrexham"):
        map_team_ids(pd.Series(["Arsenal", "Wrexham"]), ALIAS_TO_ID)


def test_every_alias_points_to_exactly_one_team() -> None:
    all_aliases = [a.casefold() for n, o in KNOWN_TEAMS.items() for a in [n, *o]]
    assert len(all_aliases) == len(set(all_aliases))


# --- date parsing --------------------------------------------------------------


def test_dates_accept_both_year_formats(cleaned: pd.DataFrame) -> None:
    assert cleaned["match_date"].tolist() == [
        date(2024, 8, 16),
        date(2024, 8, 17),
        date(2025, 2, 1),  # written "01/02/25": two-digit year, and day first
        date(2025, 5, 24),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("13/08/2016", date(2016, 8, 13)),
        ("13/08/16", date(2016, 8, 13)),
        ("01/02/2016", date(2016, 2, 1)),  # day first, never 2 January
        (" 9/8/2015 ", date(2015, 8, 9)),
    ],
)
def test_parse_match_dates(raw: str, expected: date) -> None:
    assert parse_match_dates(pd.Series([raw])).tolist() == [expected]


@pytest.mark.parametrize("raw", ["2016-08-13", "32/08/2016", "", "not a date"])
def test_parse_match_dates_rejects_garbage(raw: str) -> None:
    with pytest.raises(ValueError, match="Unparseable"):
        parse_match_dates(pd.Series([raw]))


def test_date_outside_season_is_rejected() -> None:
    raw = read_raw_csv(SAMPLE_CSV)
    with pytest.raises(ValueError, match="outside"):
        clean_results(raw, "2015-16", ALIAS_TO_ID)  # right file, wrong season


# --- stats, validation, output shape ------------------------------------------


def test_unplayed_fixture_has_null_stats(cleaned: pd.DataFrame) -> None:
    unplayed = cleaned.iloc[3]
    assert unplayed[["home_goals", "away_goals", "home_shots", "away_shots"]].isna().all()
    assert cleaned.iloc[0][["home_goals", "away_goals"]].tolist() == [1, 0]
    assert str(cleaned["home_goals"].dtype) == "Int16"


def test_output_columns_and_season(cleaned: pd.DataFrame) -> None:
    assert list(cleaned.columns) == OUTPUT_COLUMNS
    assert (cleaned["season"] == "2024-25").all()


def test_duplicate_fixture_is_rejected() -> None:
    raw = read_raw_csv(SAMPLE_CSV)
    doubled = pd.concat([raw, raw.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate fixtures"):
        clean_results(doubled, "2024-25", ALIAS_TO_ID)


def test_non_numeric_stat_is_rejected() -> None:
    raw = read_raw_csv(SAMPLE_CSV)
    raw.loc[0, "FTHG"] = "two"
    with pytest.raises(ValueError):
        clean_results(raw, "2024-25", ALIAS_TO_ID)


def test_to_records_gives_plain_python_values(cleaned: pd.DataFrame) -> None:
    records = to_records(cleaned)
    assert records[0]["home_goals"] == 1 and type(records[0]["home_goals"]) is int
    assert type(records[0]["home_team_id"]) is int
    assert records[3]["home_goals"] is None
    assert records[0]["match_date"] == date(2024, 8, 16)


# --- season codes --------------------------------------------------------------


def test_season_code_round_trip() -> None:
    assert season_label("2425") == "2024-25"
    assert season_code("2024-25") == "2425"
    assert season_label("9900") == "2099-00"


@pytest.mark.parametrize("bad", ["2426", "24-25", "abcd"])
def test_season_label_rejects_bad_codes(bad: str) -> None:
    with pytest.raises(ValueError):
        season_label(bad)
