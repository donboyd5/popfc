"""Tests for popfc.data.nchs."""

from __future__ import annotations

import pandas as pd
import pytest

from popfc.data._common import LIFE_TABLE_COLUMNS
from popfc.data.nchs import (
    DEFAULT_NY_LIFE_TABLE_TOTAL,
    DEFAULT_US_LIFE_TABLE_TOTAL,
    DEFAULT_USALEEP_NY_A,
    DEFAULT_USALEEP_NY_B,
    _parse_age_band,
    load_nchs_state_life_tables_all_sexes,
    load_nchs_us_life_tables_all_sexes,
    load_usaleep_life_expectancy,
    load_usaleep_life_table,
)


class TestParseAgeBand:
    def test_simple_range_with_en_dash(self):
        assert _parse_age_band("0–1") == (0, "0-1")

    def test_simple_range_with_ascii_hyphen(self):
        assert _parse_age_band("5-6") == (5, "5-6")

    def test_top_coded_and_over(self):
        assert _parse_age_band("100 and over") == (100, "100+")

    def test_top_coded_and_older(self):
        assert _parse_age_band("85 and older") == (85, "85+")

    def test_plus_form(self):
        assert _parse_age_band("85+") == (85, "85+")

    def test_unparseable_returns_none(self):
        assert _parse_age_band("SOURCE: National Center for Health Statistics") is None


@pytest.fixture(scope="module")
def us_lt():
    if not DEFAULT_US_LIFE_TABLE_TOTAL.exists():
        pytest.skip("US life tables not downloaded")
    return load_nchs_us_life_tables_all_sexes()


@pytest.fixture(scope="module")
def ny_lt():
    if not DEFAULT_NY_LIFE_TABLE_TOTAL.exists():
        pytest.skip("NY life tables not downloaded")
    return load_nchs_state_life_tables_all_sexes()


class TestNvsrLifeTables:
    def test_us_row_count(self, us_lt):
        # 3 sexes × 101 ages (0-1 through 100+) = 303
        assert len(us_lt) == 303

    def test_ny_row_count(self, ny_lt):
        assert len(ny_lt) == 303

    def test_schema(self, us_lt):
        assert list(us_lt.columns) == LIFE_TABLE_COLUMNS

    def test_lx_monotone_non_increasing(self, us_lt):
        for sex in ("All", "M", "F"):
            lx = us_lt[us_lt["sex"] == sex].sort_values("age")["lx"].astype(float).to_numpy()
            diffs = lx[1:] - lx[:-1]
            assert (diffs <= 0).all(), f"lx not monotone for {sex}"

    def test_us_e0_in_plausible_range(self, us_lt):
        # 2023 US life expectancy at birth is ~78.4 (NVSR 74-06).
        e0 = us_lt[us_lt["age"] == 0].set_index("sex")["ex"].astype(float)
        assert 78.0 < e0["All"] < 79.0
        assert 75.0 < e0["M"] < 76.5
        assert 80.0 < e0["F"] < 82.0

    def test_ny_e0_above_us(self, us_lt, ny_lt):
        # NY (2022) consistently has higher life expectancy than US (2023).
        e0_us = float(us_lt[(us_lt["age"] == 0) & (us_lt["sex"] == "All")]["ex"].iloc[0])
        e0_ny = float(ny_lt[(ny_lt["age"] == 0) & (ny_lt["sex"] == "All")]["ex"].iloc[0])
        assert e0_ny > e0_us


@pytest.fixture(scope="module")
def usaleep_a():
    if not DEFAULT_USALEEP_NY_A.exists():
        pytest.skip("USALEEP NY_A not downloaded")
    return load_usaleep_life_expectancy()


@pytest.fixture(scope="module")
def usaleep_b():
    if not DEFAULT_USALEEP_NY_B.exists():
        pytest.skip("USALEEP NY_B not downloaded")
    return load_usaleep_life_table(county_fips="115")


class TestUsaleep:
    def test_a_schema(self, usaleep_a):
        assert list(usaleep_a.columns) == LIFE_TABLE_COLUMNS

    def test_a_one_row_per_tract(self, usaleep_a):
        assert usaleep_a["geoid"].is_unique

    def test_b_schema(self, usaleep_b):
        assert list(usaleep_b.columns) == LIFE_TABLE_COLUMNS

    def test_b_11_age_bands_per_tract(self, usaleep_b):
        # USALEEP File B publishes 11 age bands per tract.
        per_tract = usaleep_b.groupby("geoid")["age_band"].nunique()
        assert (per_tract == 11).all()

    def test_b_washington_tract_count(self, usaleep_b):
        assert usaleep_b["geoid"].nunique() == 17

    def test_b_age_0_present_for_all_tracts(self, usaleep_b):
        tracts_with_zero = usaleep_b[usaleep_b["age"] == 0]["geoid"].nunique()
        assert tracts_with_zero == 17
